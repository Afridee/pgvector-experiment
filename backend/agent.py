"""
DATABASE AGENT
==============
Hybrid Text-to-SQL + RAG agent for answering database questions.
"""

import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import ToolMessage
from langchain.tools import tool
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector

# Load environment variables
load_dotenv()

# Configuration
READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = os.getenv("VECTOR_COLLECTION", "qmr_knowledge_chunks")

# ============================================================================
# Custom Semantic Search Tool
# ============================================================================


@tool(response_format="content_and_artifact")
def semantic_search_tool(query: str):
    """
    Search QMR knowledge chunks by semantic similarity (RAG over pgvector).

    Returns:
      - content: a human-readable ranked list
      - artifact: the raw retrieved Documents (so the caller/UI can display them)
    """
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


# ============================================================================
# Setup: SQL Database
# ============================================================================

if not READONLY_DB_URL:
    raise ValueError("READONLY_DATABASE_URL is not set (check your .env).")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set (check your .env).")

print("🔗 Connecting to SQL database...")
sql_db = SQLDatabase.from_uri(READONLY_DB_URL, sample_rows_in_table_info=2)
print("   ✓ SQL database connected")

# ============================================================================
# Setup: Vector Database
# ============================================================================

print("🔗 Connecting to vector database...")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = PGVector(
    connection=DATABASE_URL, collection_name=VECTOR_COLLECTION, embeddings=embeddings,
)
print("   ✓ Vector database connected")

# ============================================================================
# Create AI Agent with Toolkit
# ============================================================================

print("🤖 Initializing AI agent...")

llm = init_chat_model("gpt-4o", model_provider="openai", temperature=0,)

sql_toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)
all_tools = sql_toolkit.get_tools() + [semantic_search_tool]

system_prompt = """You are an expert QMR reporting/database assistant with access to powerful tools.

**SQL Tools (from toolkit):**
- sql_db_query: Execute SELECT queries (read-only)
- sql_db_schema: Get table structure
- sql_db_list_tables: List available tables
- sql_db_query_checker: Validate SQL syntax

**Custom Tools:**
- semantic_search_tool: Retrieve QMR rules, definitions, and query patterns from the embedded knowledge base (NOT product catalog search).

**Decision Guide:**
- User asks about QMR business logic ("How is Memo computed?", "What tables are queried?", "What happens when current date is in range?") → Use semantic_search_tool
- User asks about real database facts ("How many rows...", "total STT last month...", "which regions exist...") → Use sql_db_query
- User asks about schema ("what columns does X have?", "what tables exist?") → Use sql_db_list_tables or sql_db_schema
- User asks to implement a metric from rules ("Compute Memo/STT for ...") → Use BOTH:
  1) semantic_search_tool to fetch the definition and filters
  2) sql_db_schema to confirm table/column names
  3) sql_db_query to execute the final aggregation

**Rules:**
- Prefer semantic_search_tool for definitions of Memo, STT, product type behavior (SKU/Brand/Family/Segment/Total), date splitting (monthly vs daily), and filter rules.
- Prefer sql_db_schema if unsure about column names before writing SQL.
- ALWAYS use sql_db_query for numeric results.
- When answering, cite which tool you used and summarize the supporting rule or query.
- If the knowledge base conflicts with the actual schema/data, treat the database as authoritative and explain the discrepancy.
"""

agent = create_agent(model=llm, tools=all_tools, system_prompt=system_prompt)

print("   ✓ Agent ready")
print(f"   ✓ Loaded {len(all_tools)} tools")

# ============================================================================
# Main Interface
# ============================================================================


def _serialize_docs(docs: List[Any]) -> List[Dict[str, Any]]:
    """Convert LangChain Document objects into JSON-serializable dicts for the UI."""
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
                "preview": content[:800],  # UI can truncate further
                "metadata": meta,
            }
        )
    return serialized


def ask_database(question: str) -> Dict[str, Any]:
    """
    Ask a question to the database agent.

    Returns a dict for richer UIs (Streamlit):
      {
        "answer": <final assistant text>,
        "artifacts": {
            "semantic_search_docs": [ ... ]   # present only if available
        },
        "raw": <raw agent output (optional)>
      }
    """
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        answer = result["messages"][-1].content

        artifacts: Dict[str, Any] = {}

        tool_messages = result.get("messages", [])
        semantic_docs: List[Any] = []

        for message in tool_messages:
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

        return {
            "answer": answer,
            "artifacts": artifacts,
            "raw": result,  # keep for debugging; Streamlit can hide unless toggled
        }

    except Exception as e:
        return {"answer": f"❌ Error: {str(e)}", "artifacts": {}, "raw": None}


def main():
    """Main interactive loop (CLI)."""
    print("\n" + "=" * 70)
    print("QMR DATABASE + KNOWLEDGE AGENT")
    print("=" * 70)
    print("\nType 'quit', 'exit', or 'q' to exit")
    print("=" * 70 + "\n")

    while True:
        question = input("❓ Your question: ").strip()

        if question.lower() in ["quit", "exit", "q"]:
            print("\nGoodbye!")
            break

        if not question:
            continue

        print("\nThinking...\n")
        res = ask_database(question)
        print(f"\nAnswer:\n{res['answer']}\n")
        if res.get("artifacts", {}).get("semantic_search_docs"):
            print(
                "(Retrieved knowledge chunks: "
                f"{len(res['artifacts']['semantic_search_docs'])})"
            )
        print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
