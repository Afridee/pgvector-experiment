"""
DATABASE AGENT
==============
Hybrid Text-to-SQL + RAG agent for answering database questions.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import ToolMessage
from langchain.tools import tool
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver

load_dotenv()

READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = os.getenv("VECTOR_COLLECTION", "qmr_knowledge_chunks")
CHECKPOINT_DB_URL = os.getenv("CHECKPOINT_DB_URL", DATABASE_URL)

if not READONLY_DB_URL:
    raise ValueError("READONLY_DATABASE_URL is not set (check your .env).")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set (check your .env).")
if not CHECKPOINT_DB_URL:
    raise ValueError("CHECKPOINT_DB_URL is not set (check your .env).")

# ----------------------------------------------------------------------------
# Globals (singleton agent + open context manager)
# ----------------------------------------------------------------------------
_AGENT = None
_CHECKPOINTER_CM = None  # context manager object
_CHECKPOINTER = None  # entered saver instance


@tool(response_format="content_and_artifact")
def semantic_search_tool(query: str):
    """Search QMR knowledge chunks by semantic similarity (RAG over pgvector)."""
    try:
        docs = vectorstore.similarity_search(query, k=5)
        if not docs:
            return "No similar QMR knowledge found.", []

        results = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata or {}
            title = meta.get("title") or f"Chunk {meta.get('chunk_index', 'N/A')}"
            tags = meta.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            source_file = (
                meta.get("source_file") or meta.get("source_path") or "unknown"
            )
            chunk_index = meta.get("chunk_index", "N/A")

            preview = " ".join((doc.page_content or "").split())
            if len(preview) > 400:
                preview = preview[:400].rstrip() + "..."

            results.append(
                f"{i}. {title}\n"
                f"   Tags: {', '.join(tags) if tags else 'N/A'}\n"
                f"   Source: {source_file} (chunk {chunk_index})\n"
                f"   Preview: {preview}"
            )

        return "\n\n".join(results), docs
    except Exception as e:
        return f"❌ Error in semantic_search_tool: {str(e)}", []


print("🔗 Connecting to SQL database...")
sql_db = SQLDatabase.from_uri(READONLY_DB_URL, sample_rows_in_table_info=2)
print("   ✓ SQL database connected")

print("🔗 Connecting to vector database...")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = PGVector(
    connection=DATABASE_URL, collection_name=VECTOR_COLLECTION, embeddings=embeddings,
)
print("   ✓ Vector database connected")

llm = init_chat_model("gpt-4o", model_provider="openai", temperature=0)

sql_toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)
all_tools = sql_toolkit.get_tools() + [semantic_search_tool]

# ----------------------------------------------------------------------------
# Updated System Prompt (QMR SQL rules + output contract)
# ----------------------------------------------------------------------------
system_prompt = """
You are an expert QMR (Outlet Query Manager Report) database assistant.

You have access to:
- SQL tools for querying the database (READ-ONLY)
- semantic_search_tool() which retrieves authoritative “QMR semantic knowledge chunks”.
Always follow the knowledge chunks when they apply; they override generic SQL instincts.

# Absolute QMR SQL rules (non-negotiable)
1) Allowed sources ONLY (for primary/retailer queries):
   - monthly_order_cache_YYYY_MM (materialized monthly cache tables)
   - daily_order_cache (live cache)
   Do NOT use any other tables or joins in the QMR primary/retailer queries.

2) You MUST output two SQL queries for QMR requests:
   - primaryDataQuery (required)
   - retailerOrderDataQuery (required)
     If productType = Total, retailerOrderDataQuery MUST be:
       SELECT 1 as "Dummy"

3) Date filtering MUST be inclusive lower bound and exclusive upper bound:
   - o.order_placed_at >= lower
   - o.order_placed_at < upper

4) Date split (MV vs daily):
   - Define: endDatePlusOne = endDate + 1 day (exclusive overall upper bound)
   - Define: currentDate = today's date (server/local date used by the app)
   If startDate <= currentDate <= endDate:
     - MV portion uses monthly tables with upper bound = currentDate (exclusive)
     - Daily portion uses daily_order_cache from currentDate (inclusive) to endDatePlusOne (exclusive)
   Else:
     - Use ONLY monthly tables from startDate (inclusive) to endDatePlusOne (exclusive)
     - Do NOT query daily_order_cache

5) ProductType normalization and mapping:
   Normalize productType into one of: SKU, Brand, Family, Segment, Total.
   Field mapping:
   - SKU     -> o.sku_id
   - Brand   -> o.brand_id
   - Family  -> o.family_id
   - Segment -> o.segment_id
   - Total   -> (no product field)
   If productType != Total:
     include product id in SELECT + GROUP BY, and include it in the primary memo distinct key.
   If productType = Total:
     do not select/group by product id and do not append product id to the memo distinct key.

6) Memo distinct key rules:
   - Primary query memo distinct key:
     retailer_id + DATE(order_placed_at) + optional product_id (only when productType != Total)
   - Retailer order query "Total Memo" distinct key:
     retailer_id + DATE(order_placed_at) (NEVER includes product_id)

7) Filters:
   Filters are optional AND-clauses only; ignore empty lists and ignore lists that contain "all".
   Mapping:
   - regionFilter       -> AND o.region_id IN (...)
   - areaFilter         -> AND o.area_id IN (...)
   - distributorFilter  -> AND o.house_id IN (...)
   - territoryFilter    -> AND o.territory_id IN (...)
   - pointFilter        -> AND o.point_id IN (...)
   - subChannelFilter   -> AND o.sub_channel_id IN (...)
   - productFilter      -> AND o.<productField> IN (...) per ProductType mapping
   Combine as {filtersSql} (each line begins with AND).

# How to respond
- If the user asks for a QMR report / QMR SQL, first use semantic_search_tool to retrieve any relevant chunks
  (e.g., “QMR SQL Template Overview”, “ProductType mapping”, “Date split rules”, “Primary query template”, etc.).
- Then produce:
  1) primaryDataQuery SQL
  2) retailerOrderDataQuery SQL
- Use the template structure from the knowledge (per-table SELECTs UNION ALL then an outer aggregate).
- For monthly tables, include only the months that intersect the MV portion.
- If you need IDs (region_id, point_id, brand_id, etc.) but the user only provides names,
  ask a clarification OR (if allowed in your environment) use a separate lookup query.
  However: do NOT introduce joins inside the QMR primary/retailer queries.

# Output format (strict)
Return a JSON object with:
{
  "primaryDataQuery": "<SQL string>",
  "retailerOrderDataQuery": "<SQL string>",
  "notes": ["any important assumptions, e.g., resolved IDs, currentDate used, months selected"]
}
""".strip()


def get_agent():
    """
    Streamlit-safe singleton:
    - keeps the PostgresSaver context open for the lifetime of the process
    - creates the agent once
    """
    global _AGENT, _CHECKPOINTER_CM, _CHECKPOINTER

    if _AGENT is not None:
        return _AGENT

    # Enter the context manager ONCE and never exit it until process shutdown
    _CHECKPOINTER_CM = PostgresSaver.from_conn_string(CHECKPOINT_DB_URL)
    _CHECKPOINTER = _CHECKPOINTER_CM.__enter__()

    if not isinstance(_CHECKPOINTER, BaseCheckpointSaver):
        raise TypeError(f"Expected BaseCheckpointSaver, got {type(_CHECKPOINTER)}")

    # Run setup once at startup
    _CHECKPOINTER.setup()

    _AGENT = create_agent(
        model=llm,
        tools=all_tools,
        system_prompt=system_prompt,
        checkpointer=_CHECKPOINTER,
    )
    return _AGENT


def _serialize_docs(docs: List[Any]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for d in docs or []:
        meta = getattr(d, "metadata", None) or {}
        content = getattr(d, "page_content", "") or ""
        serialized.append(
            {
                "title": meta.get("title"),
                "tags": meta.get("tags"),
                "chunk_index": meta.get("chunk_index"),
                "source_file": meta.get("source_file"),
                "source_path": meta.get("source_path"),
                "type": meta.get("type"),
                "preview": content[:800],
                "metadata": meta,
            }
        )
    return serialized


def ask_database(question: str, thread_id: str) -> Dict[str, Any]:
    agent = get_agent()

    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"configurable": {"thread_id": thread_id}},
    )

    answer = result["messages"][-1].content

    artifacts: Dict[str, Any] = {}
    semantic_docs: List[Any] = []

    for message in result.get("messages", []):
        if not isinstance(message, ToolMessage):
            continue

        tool_name = (
            getattr(message, "name", None)
            or getattr(message, "tool", None)
            or getattr(message, "tool_name", None)
        )
        artifact = getattr(message, "artifact", None)

        if (
            tool_name == "semantic_search_tool"
            and isinstance(artifact, list)
            and artifact
        ):
            semantic_docs.extend(artifact)

    if semantic_docs:
        artifacts["semantic_search_docs"] = _serialize_docs(semantic_docs)

    return {"answer": answer, "artifacts": artifacts, "raw": result}
