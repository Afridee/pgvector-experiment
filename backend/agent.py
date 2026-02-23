"""
DATABASE AGENT
==============
Hybrid Text-to-SQL + RAG agent for answering database questions.
"""

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector

# Load environment variables
load_dotenv()

# Configuration
READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = "qmr_knowledge_chunks"

# ============================================================================
# Custom Semantic Search Tool
# ============================================================================


@tool(response_format="content_and_artifact")
def semantic_search_tool(query: str) -> str:
    """
    Search QMR knowledge chunks by semantic similarity (RAG over pgvector).

    Intended use:
    - "How is Memo calculated?"
    - "What tables are queried for current date?"
    - "What filters exist for region/area/territory?"
    - "Which generator runs for Brand vs SKU?"

    Returns a readable ranked list of matching knowledge chunks.
    """
    try:
        docs = vectorstore.similarity_search(query, k=5)

        if not docs:
            return "No similar QMR knowledge found."

        results = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata or {}

            title = meta.get("title") or f"Chunk {meta.get('chunk_index', 'N/A')}"
            tags = meta.get("tags") or []
            if isinstance(tags, str):
                # In case tags were stored as a comma-separated string
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            source_file = (
                meta.get("source_file") or meta.get("source_path") or "unknown"
            )
            chunk_index = meta.get("chunk_index", "N/A")

            # Make a compact preview (first ~400 chars)
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
        return f"❌ Error in semantic_search_tool: {str(e)}"


# ============================================================================
# Setup: SQL Database
# ============================================================================

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

# Initialize LLM
llm = init_chat_model(
    "gpt-4o",  # or "gpt-4-turbo"
    model_provider="openai",
    temperature=0,  # Deterministic for database queries
)

# Create SQL toolkit (provides multiple SQL tools)
sql_toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)

# Get all tools from toolkit + add custom semantic search
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

agent = create_agent(model=llm, tools=all_tools, system_prompt=system_prompt,)

print("   ✓ Agent ready")
print(f"   ✓ Loaded {len(all_tools)} tools")

# ============================================================================
# Main Interface
# ============================================================================


def ask_database(question: str) -> str:
    """Ask a question to the database agent."""
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        return result["messages"][-1].content
    except Exception as e:
        return f"❌ Error: {str(e)}"


def main():
    """Main interactive loop."""
    print("\n" + "=" * 70)
    print("QMR DATABASE + KNOWLEDGE AGENT")
    print("=" * 70)
    print("\nCapabilities:")
    print(
        "  ✓ SQL queries (counts, filters, joins, aggregations) on the reporting database"
    )
    print("  ✓ Schema inspection (tables, columns)")
    print(
        "  ✓ QMR semantic knowledge search (Memo/STT definitions, date-splitting rules, filters)"
    )
    print("  ✓ Hybrid reasoning (retrieve QMR rules, then validate/compute with SQL)")
    print("\nExample questions:")
    print("  1. What tables are available?")
    print("  2. How is 'Memo' calculated for SKU vs Total?")
    print("  3. What happens if today's date is within the requested date range?")
    print(
        "  4. What filters are supported (region/area/territory/subChannel/activeStatus)?"
    )
    print(
        "  5. Which tables are used: monthly_order_cache_YYYY_MM vs daily_order_cache?"
    )
    print("\nType 'quit', 'exit', or 'q' to exit")
    print("=" * 70 + "\n")

    while True:
        question = input("❓ Your question: ").strip()

        if question.lower() in ["quit", "exit", "q"]:
            print("\n👋 Goodbye!")
            break

        if not question:
            continue

        print("\n🤔 Thinking...\n")
        answer = ask_database(question)
        print(f"\n💡 Answer:\n{answer}\n")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
