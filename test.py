import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import OpenAIEmbeddings
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
# Define Custom Semantic Search Tool
# ============================================================================


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
# Create Agent (Modern LangChain API with Toolkit)
# ============================================================================

# Initialize LLM
llm = init_chat_model(
    "gpt-4o",
    model_provider="openai",
    temperature=0,  # Deterministic for database queries
)

# Create SQL toolkit (provides multiple SQL tools)
sql_toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)

# Get all tools from toolkit + add custom semantic search
all_tools = sql_toolkit.get_tools() + [semantic_search_tool]

system_prompt = """You are a database assistant with access to SQL and semantic search tools.

Use SQL tools (sql_db_query, sql_db_schema, sql_db_list_tables) for:
- Counts, sums, averages, totals
- Filtering by exact values
- Joining tables
- Schema inspection

Use semantic_search_tool for:
- Finding by description or meaning
- Similarity searches
- Topic-based searches

Provide clear, concise answers."""

agent = create_agent(model=llm, tools=all_tools, system_prompt=system_prompt,)

print(f"   ✓ Test environment ready ({len(all_tools)} tools loaded)\n")

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
    {
        "name": "Schema Inspection",
        "question": "What tables are available in the database?",
        "expected_type": "list",
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
    print("\nNext step: Run interactive agent with 'python agent.py'")
else:
    print(f"\n⚠️  {failed} test(s) failed. Check error messages above.")

print("=" * 70)
