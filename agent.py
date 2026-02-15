"""
DATABASE AGENT
==============
Text-to-SQL agent for answering database questions.
"""

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase

# Load environment variables
load_dotenv()

# Configuration
READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")

# ============================================================================
# Setup: SQL Database
# ============================================================================

print("🔗 Connecting to SQL database...")
sql_db = SQLDatabase.from_uri(READONLY_DB_URL, sample_rows_in_table_info=2)
print("   ✓ SQL database connected")

# ============================================================================
# Create AI Agent with Toolkit
# ============================================================================

print("🤖 Initializing AI agent...")

# Initialize LLM
llm = init_chat_model(
    "gpt-4o",
    model_provider="openai",
    temperature=0,  # Deterministic for database queries
)

# Create SQL toolkit (provides multiple SQL tools)
sql_toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)

# Get all SQL tools
all_tools = sql_toolkit.get_tools()

system_prompt = """You are an expert database assistant with access to SQL tools.

**Available Tools:**
- sql_db_query: Execute SELECT queries
- sql_db_schema: Get table structure
- sql_db_list_tables: List available tables
- sql_db_query_checker: Validate SQL syntax

**Decision Guide:**
- User asks "how many", "total", "average", "sum" → Use sql_db_query
- User asks "what tables", "schema" → Use sql_db_list_tables or sql_db_schema

**Rules:**
- Check table schemas first if you're unsure about column names
- ALWAYS use sql_db_query for numerical operations
- Only generate SELECT queries (read-only)
- Provide clear, concise answers
"""

agent = create_agent(
    model=llm,
    tools=all_tools,
    system_prompt=system_prompt,
)

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
    print("DATABASE QUESTION ANSWERING AGENT")
    print("=" * 70)
    print("\n✨ Capabilities:")
    print("  ✓ SQL queries (counts, filters, joins, aggregations)")
    print("  ✓ Schema inspection (tables, columns)")
    print("\n💡 Example questions:")
    print("  1. What tables are available?")
    print("  2. How many products are in stock?")
    print("  3. What's the total revenue from all orders?")
    print("  4. What are the top 3 best-selling products?")
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
