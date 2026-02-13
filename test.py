import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector

load_dotenv()

READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = "text_embeddings"

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
# Define Tools (Plain Python Functions)
# ============================================================================


def sql_query_tool(query: str) -> str:
    """Execute SQL SELECT queries on the database."""
    try:
        query_upper = query.upper().strip()
        if not query_upper.startswith("SELECT"):
            return "❌ Only SELECT queries are allowed"

        forbidden = [
            "DROP",
            "DELETE",
            "TRUNCATE",
            "INSERT",
            "UPDATE",
            "ALTER",
            "CREATE",
            "GRANT",
            "REVOKE",
            "EXEC",
            "EXECUTE",
        ]
        for keyword in forbidden:
            if keyword in query_upper:
                return f"❌ Forbidden keyword: {keyword}"

        result = sql_db.run(query)
        return result if result else "No results found"
    except Exception as e:
        return f"❌ Error: {str(e)}"


def semantic_search_tool(query: str) -> str:
    """Search database text content by semantic similarity."""
    try:
        docs = vectorstore.similarity_search(query, k=3)
        if not docs:
            return "No similar content found"

        results = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata
            content_preview = doc.page_content[:150]
            results.append(
                f"{i}. {meta.get('name', 'N/A')} [{meta.get('source_table', 'unknown')}]\n"
                f"   {content_preview}..."
            )

        return "\n\n".join(results)
    except Exception as e:
        return f"❌ Error: {str(e)}"


# ============================================================================
# Create Agent (Modern LangChain API)
# ============================================================================

system_prompt = """You are a database assistant. 

Use sql_query_tool for:
- Counts, sums, averages, totals
- Filtering by exact values
- Joining tables

Use semantic_search_tool for:
- Finding by description or meaning
- Similarity searches
- Topic-based searches

Provide clear, concise answers."""

agent = create_agent(
    model="gpt-4",
    tools=[sql_query_tool, semantic_search_tool],
    system_prompt=system_prompt,
)

print("   ✓ Test environment ready\n")

# ============================================================================
# Test Cases
# ============================================================================

test_cases = [
    {
        "name": "SQL Count Query",
        "question": "How many products are in the database?",
        "expected_type": "number",
    },
    {
        "name": "SQL Aggregation Query",
        "question": "What's the total revenue from all orders?",
        "expected_type": "number",
    },
    {
        "name": "Semantic Search - Products",
        "question": "Find products good for gaming",
        "expected_type": "list",
    },
    {
        "name": "Semantic Search - Reviews",
        "question": "Show me reviews mentioning battery",
        "expected_type": "text",
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

    try:
        # Invoke agent with new API
        result = agent.invoke(
            {"messages": [{"role": "user", "content": test["question"]}]}
        )

        # Extract answer from response
        answer = result["messages"][-1].content

        # Display result
        print(f"\n   ✅ Answer: {answer[:200]}")
        if len(answer) > 200:
            print(f"      ... (truncated, full length: {len(answer)} chars)")

        passed += 1

    except Exception as e:
        print(f"\n   ❌ FAILED: {str(e)}")
        failed += 1

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
    print("\nNext step: Run interactive agent with 'python 02_agent.py'")
else:
    print(f"\n⚠️  {failed} test(s) failed. Check error messages above.")

print("=" * 70)
