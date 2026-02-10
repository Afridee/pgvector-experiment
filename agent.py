"""
DATABASE AGENT
==============
Hybrid Text-to-SQL + RAG agent for answering database questions.
"""

import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.utilities import SQLDatabase
from langchain_postgres.vectorstores import PGVector
from langchain.agents import create_agent

# Load environment variables
load_dotenv()

# Configuration
READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = "text_embeddings"

# ... (keep all your validation and setup code) ...

# ============================================================================
# Tool Functions (convert to regular Python functions)
# ============================================================================

def sql_query_tool(query: str) -> str:
    """
    Execute SQL SELECT queries on the database.
    
    Use for:
    - Counting: "How many orders?"
    - Aggregations: "Total revenue", "Average price"
    - Filtering: "Products over $100"
    - Joins: "Customers and their orders"
    - Exact matches: Dates, IDs, categories
    """
    try:
        # Validate query for security
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT"):
            return "❌ Only SELECT queries are allowed"
        
        forbidden = ["DROP", "DELETE", "TRUNCATE", "INSERT", "UPDATE", "ALTER", "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE"]
        for keyword in forbidden:
            if keyword in query_upper:
                return f"❌ Forbidden keyword: {keyword}"
        
        # Execute query
        result = sql_db.run(query)
        return result if result else "No results found"
        
    except Exception as e:
        return f"❌ Error: {str(e)}"


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
    connection=DATABASE_URL,
    collection_name=VECTOR_COLLECTION,
    embeddings=embeddings,
)
print("   ✓ Vector database connected")

# ============================================================================
# Create AI Agent (Official 2025 API)
# ============================================================================

print("🤖 Initializing AI agent...")

system_prompt = """You are an expert database assistant with access to two powerful tools:

1. **sql_query_tool**: For structured queries (counts, sums, averages, filters, joins)
2. **semantic_search_tool**: For finding content by description or meaning

**Decision Guide:**
- User asks "how many", "total", "average", "sum" → Use sql_query_tool
- User asks "find products about X", "similar to Y" → Use semantic_search_tool
- User asks "top selling products like X" → Use BOTH tools:
  1. First, semantic_search_tool to find relevant product IDs
  2. Then, sql_query_tool to get sales data and rank them

**Rules:**
- ALWAYS use sql_query_tool for numerical operations
- ALWAYS use semantic_search_tool for descriptive/semantic queries
- You can use BOTH tools in sequence for complex queries
- Provide clear, concise answers
- Be helpful and friendly
"""

agent = create_agent(
    model="gpt-4",
    tools=[sql_query_tool, semantic_search_tool],
    system_prompt=system_prompt,
)

print("   ✓ Agent ready")

# ============================================================================
# Main Interface
# ============================================================================

def ask_database(question: str) -> str:
    """Ask a question to the database agent."""
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        # Extract the last message content
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
    print("  ✓ Semantic search (find by description)")
    print("  ✓ Hybrid queries (combine both approaches)")
    print("\n💡 Example questions:")
    print("  1. How many products are in stock?")
    print("  2. What's the total revenue from all orders?")
    print("  3. Find products good for gaming")
    print("  4. What are the top 3 best-selling products?")
    print("  5. Show me reviews mentioning battery life")
    print("\nType 'quit', 'exit', or 'q' to exit")
    print("=" * 70 + "\n")
    
    while True:
        question = input("❓ Your question: ").strip()
        
        if question.lower() in ['quit', 'exit', 'q']:
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