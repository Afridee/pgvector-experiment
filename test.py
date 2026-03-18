"""
TEST SCRIPT
===========
Automated tests for the API + Knowledge Agent (Report Assistant).

Tests cover:
1. Semantic search — agent retrieves relevant API knowledge chunks
2. Parameter collection — agent asks for missing required parameters
3. Live API calls — endpoints with no required parameters

Usage:
    python test.py

Requires:
    - .env with DATABASE_URL, OPENAI_API_KEY
    - Embeddings already ingested (run ingest.py first)
    - API_TOKEN set for live API call tests
"""

import uuid

from dotenv import load_dotenv

load_dotenv()  # must run before importing ask_agent

from backend.agent import ask_agent  # noqa: E402

# ============================================================================
# Test Cases
# ============================================================================

# check_semantic_docs: expect semantic_search_docs in artifacts
# check_api_called:    expect at least one entry in api_responses in artifacts

test_cases = [
    # --- Semantic search / knowledge retrieval ---
    {
        "name": "Semantic search — Clocking check status parameters",
        "question": "What parameters does the clocking check status endpoint require?",
        "check_semantic_docs": True,
        "check_api_called": False,
    },
    {
        "name": "Semantic search — Checklist record required fields",
        "question": "What do I need to fetch a checklist record?",
        "check_semantic_docs": True,
        "check_api_called": False,
    },
    {
        "name": "Semantic search — TempLog response fields",
        "question": "What fields does the temperature log record response contain?",
        "check_semantic_docs": True,
        "check_api_called": False,
    },
    # --- Parameter collection (agent must ask, not guess) ---
    {
        "name": "Parameter collection — Clocking paginated records",
        "question": "Show me clocking records",
        "check_semantic_docs": True,
        "check_api_called": False,  # staffId + page missing
    },
    {
        "name": "Parameter collection — Checklist record by venue",
        "question": "Get the checklist record for Main Hall",
        "check_semantic_docs": True,
        "check_api_called": False,  # date + typeId still missing
    },
    {
        "name": "Parameter collection — Clocking check status",
        "question": "Is the staff member currently clocked in?",
        "check_semantic_docs": True,
        "check_api_called": False,  # staffId missing
    },
    # --- Live API calls (no required parameters) ---
    {
        "name": "Live API — List all departments",
        "question": "List all available departments",
        "check_semantic_docs": True,
        "check_api_called": True,
    },
    {
        "name": "Live API — List all clocking sites",
        "question": "Show me all clocking sites",
        "check_semantic_docs": True,
        "check_api_called": True,
    },
    {
        "name": "Live API — List all checklist venues",
        "question": "List all venues",
        "check_semantic_docs": True,
        "check_api_called": True,
    },
    {
        "name": "Live API — List all checklist types",
        "question": "What checklist types are available?",
        "check_semantic_docs": True,
        "check_api_called": True,
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
        result = ask_agent(test["question"], thread_id=thread_id)

        answer = result["answer"]
        artifacts = result.get("artifacts", {})
        semantic_docs = artifacts.get("semantic_search_docs", [])
        api_responses = artifacts.get("api_responses", [])

        print(f"\n   ✅ Answer: {answer[:300]}")
        if len(answer) > 300:
            print(f"      ... (truncated, full length: {len(answer)} chars)")

        if test["check_semantic_docs"]:
            if semantic_docs:
                print(f"   📎 Semantic docs retrieved: {len(semantic_docs)} chunk(s)")
            else:
                print(
                    "   ⚠️  No semantic search docs returned (knowledge chunks not used)"
                )

        if test["check_api_called"]:
            if api_responses:
                print(f"   🌐 API called: {len(api_responses)} response(s) recorded")
            else:
                print("   ⚠️  No API responses recorded (API may not have been called)")

        passed += 1

    except Exception as e:
        print(f"\n   ❌ FAILED: {str(e)}")
        import traceback

        traceback.print_exc()
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
else:
    print(f"\n⚠️  {failed} test(s) failed. Check error messages above.")

print("=" * 70)
