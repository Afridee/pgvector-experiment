"""
DATABASE AGENT
==============
Hybrid Text-to-SQL + RAG agent for answering database questions.
"""

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector

# Load environment variables
load_dotenv()

# Configuration
READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = "text_embeddings"

# ============================================================================
# Custom Semantic Search Tool
# ============================================================================


def semantic_search_tool(query: str) -> str:
    """
    Search database text content by semantic similarity.
    
    Use for:
    - Finding by description: "products for gaming"
    - Similarity: "items like laptops"
    - Topic search: "reviews about battery"
    """
    try:
        docs = vectorstore.similarity_search(query, k=5)

        if not docs:
            return "No similar content found"

        results = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata
            content_preview = doc.page_content[:200]

            results.append(
                f"{i}. {meta.get('name', 'N/A')} [{meta.get('source_table', 'unknown')}]\n"
                f"   {content_preview}...\n"
                f"   (ID: {meta.get('id', 'N/A')})"
            )

        return "\n\n".join(results)

    except Exception as e:
        return f"❌ Error: {str(e)}"


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

system_prompt = """You are an expert database assistant with access to powerful tools:

**SQL Tools (from toolkit):**
- sql_db_query: Execute SELECT queries
- sql_db_schema: Get table structure
- sql_db_list_tables: List available tables
- sql_db_query_checker: Validate SQL syntax

**Custom Tools:**
- semantic_search_tool: Find content by description or meaning

**Decision Guide:**
- User asks "how many", "total", "average", "sum" → Use sql_db_query
- User asks "what tables", "schema" → Use sql_db_list_tables or sql_db_schema
- User asks "find products about X", "similar to Y" → Use semantic_search_tool
- User asks "top selling products like X" → Use BOTH:
  1. First, semantic_search_tool to find relevant product IDs
  2. Then, sql_db_query to get sales data and rank them

**Rules:**
- Check table schemas first if you're unsure about column names
- ALWAYS use sql_db_query for numerical operations
- ALWAYS use semantic_search_tool for descriptive/semantic queries
- You can use multiple tools in sequence for complex queries
- Provide clear, concise answers
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
    print("DATABASE QUESTION ANSWERING AGENT")
    print("=" * 70)
    print("\n✨ Capabilities:")
    print("  ✓ SQL queries (counts, filters, joins, aggregations)")
    print("  ✓ Schema inspection (tables, columns)")
    print("  ✓ Semantic search (find by description)")
    print("  ✓ Hybrid queries (combine both approaches)")
    print("\n💡 Example questions:")
    print("  1. What tables are available?")
    print("  2. How many products are in stock?")
    print("  3. What's the total revenue from all orders?")
    print("  4. Find products good for gaming")
    print("  5. What are the top 3 best-selling products?")
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
