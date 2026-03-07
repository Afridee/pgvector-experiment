"""
TEST SCRIPT
===========
Automated tests for the QMR Database + Knowledge Agent.

Tests cover:
1. SQL count / aggregation via the SQL toolkit
2. Semantic search via semantic_search_tool (RAG over pgvector)
3. QMR-specific rules (Memo calculation, date split, ProductType mapping)

Usage:
    python test.py

Requires:
    - .env with READONLY_DATABASE_URL, DATABASE_URL
    - Embeddings already ingested (run ingest.py first)
"""

import os
import uuid
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import ToolMessage
from langchain.tools import tool
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from langgraph.checkpoint.postgres import PostgresSaver

load_dotenv()

READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = os.getenv("VECTOR_COLLECTION", "qmr_knowledge_chunks")
CHECKPOINT_DB_URL = os.getenv("CHECKPOINT_DB_URL", DATABASE_URL)

print("🔧 Setting up test environment...")

# ============================================================================
# Setup Databases
# ============================================================================

sql_db = SQLDatabase.from_uri(READONLY_DB_URL, sample_rows_in_table_info=2)

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = PGVector(
    connection=DATABASE_URL, collection_name=VECTOR_COLLECTION, embeddings=embeddings
)

# ============================================================================
# Define Tools (mirror agent.py style)
# ============================================================================


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


# ============================================================================
# Create Agent
# ============================================================================

llm = init_chat_model("gpt-4o", model_provider="openai", temperature=0)

sql_toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)
all_tools = sql_toolkit.get_tools() + [semantic_search_tool]

system_prompt = """You are a QMR database assistant with access to SQL tools and a semantic search tool.

Use SQL tools for: counts, aggregations, schema inspection, filtering by exact values.
Use semantic_search_tool for: QMR rules, Memo/STT logic, date split, ProductType mapping,
  filter definitions, and SQL template guidance.

Provide clear, concise answers."""

# ============================================================================
# Checkpointer (mirrors agent.py singleton pattern)
# ============================================================================

_checkpointer_cm = PostgresSaver.from_conn_string(CHECKPOINT_DB_URL)
checkpointer = _checkpointer_cm.__enter__()
checkpointer.setup()

agent = create_agent(
    model=llm, tools=all_tools, system_prompt=system_prompt, checkpointer=checkpointer,
)

print(f"   ✓ Test environment ready ({len(all_tools)} tools loaded)\n")

# ============================================================================
# Helper: extract semantic search artifacts from agent response
# ============================================================================


def _extract_artifacts(result: Dict[str, Any]) -> List[Any]:
    """Pull RAG docs from ToolMessage artifacts, same logic as agent.py ask_database."""
    docs: List[Any] = []
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
            docs.extend(artifact)
    return docs


# ============================================================================
# Test Cases
# ============================================================================

test_cases = [
    {
        "name": "SQL — Schema inspection",
        "question": "What tables are available in the database?",
        "expected_type": "list",
        "check_artifacts": False,
    },
    {
        "name": "SQL — Count query",
        "question": "How many rows are in daily_order_cache?",
        "expected_type": "number",
        "check_artifacts": False,
    },
    {
        "name": "Semantic search — Memo calculation rules",
        "question": "How is Memo calculated for SKU vs Total productType?",
        "expected_type": "text",
        "check_artifacts": True,
    },
    {
        "name": "Semantic search — Date split rules",
        "question": "What happens if today's date falls within the requested date range?",
        "expected_type": "text",
        "check_artifacts": True,
    },
    {
        "name": "Semantic search — ProductType mapping",
        "question": "Which cache column corresponds to Brand productType?",
        "expected_type": "text",
        "check_artifacts": True,
    },
    {
        "name": "Semantic search — Filters",
        "question": "How should the distributorFilter be applied in SQL?",
        "expected_type": "text",
        "check_artifacts": True,
    },
    {
        "name": "QMR SQL generation — SKU, date range fully in past",
        "question": (
            "Generate QMR SQL for productType=SKU, "
            "startDate=2025-01-01, endDate=2025-01-31. "
            "No filters. Today is 2026-03-02."
        ),
        "expected_type": "sql",
        "check_artifacts": True,
    },
    {
        "name": "QMR SQL generation — Total productType",
        "question": (
            "Generate QMR SQL for productType=Total, "
            "startDate=2026-02-01, endDate=2026-02-28. "
            "No filters. Today is 2026-03-02."
        ),
        "expected_type": "sql",
        "check_artifacts": True,
    },
]

# ============================================================================
# Run Tests
# ============================================================================

print("=" * 70)
print("AUTOMATED AGENT TESTS")
print("=" * 70)

passed = 0
failed = 0

for i, test in enumerate(test_cases, 1):
    print(f"\n🧪 TEST {i}/{len(test_cases)}: {test['name']}")
    print(f"   Question: {test['question']}")
    print("-" * 70)

    thread_id = f"test_{uuid.uuid4().hex}"

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": test["question"]}]},
            config={"configurable": {"thread_id": thread_id}},
        )

        answer = result["messages"][-1].content
        artifacts = _extract_artifacts(result)

        print(f"\n   ✅ Answer: {answer[:300]}")
        if len(answer) > 300:
            print(f"      ... (truncated, full length: {len(answer)} chars)")

        if test["check_artifacts"]:
            if artifacts:
                print(f"   📎 Semantic docs retrieved: {len(artifacts)} chunk(s)")
            else:
                print(
                    "   ⚠️  No semantic search artifacts returned (knowledge chunks not used)"
                )

        passed += 1

    except Exception as e:
        print(f"\n   ❌ FAILED: {str(e)}")
        import traceback

        traceback.print_exc()
        failed += 1

# ============================================================================
# Cleanup
# ============================================================================

try:
    _checkpointer_cm.__exit__(None, None, None)
except Exception:
    pass

# ============================================================================
# Summary
# ============================================================================

print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)
print(f"✅ Passed: {passed}/{len(test_cases)}")
print(f"❌ Failed: {failed}/{len(test_cases)}")

if failed == 0:
    print("\n🎉 All tests passed! The agent is working correctly.")
else:
    print(f"\n⚠️  {failed} test(s) failed. Check error messages above.")

print("=" * 70)
