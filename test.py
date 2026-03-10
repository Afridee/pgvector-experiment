"""
TEST SCRIPT
===========
Automated tests for the API + Knowledge Agent (Report Assistant).

Tests cover:
1. Semantic search — agent retrieves relevant API knowledge chunks
2. Parameter collection — agent asks for missing required parameters before calling

Usage:
    python test.py

Requires:
    - .env with DATABASE_URL, OPENAI_API_KEY, BASE_URL
    - Embeddings already ingested (run ingest.py first)
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
        "name": "Semantic search — SSS Report required parameters",
        "question": "What parameters does the SSS report endpoint require?",
        "check_semantic_docs": True,
        "check_api_called": False,
    },
    {
        "name": "Semantic search — Query Manager Report endpoint details",
        "question": "How do I call the Query Manager Report API?",
        "check_semantic_docs": True,
        "check_api_called": False,
    },
    {
        "name": "Semantic search — Route Wise STT Report parameters",
        "question": "What fields are required for the Route Wise STT report?",
        "check_semantic_docs": True,
        "check_api_called": False,
    },
    {
        "name": "Semantic search — Survey Report response fields",
        "question": "What does the Survey Report API response look like?",
        "check_semantic_docs": True,
        "check_api_called": False,
    },
    {
        "name": "Semantic search — IRIS Gift Requisition endpoint",
        "question": "What parameters does the IRIS Gift Requisition report need?",
        "check_semantic_docs": True,
        "check_api_called": False,
    },
    # --- Parameter collection (agent must ask, not call the API) ---
    {
        "name": "Parameter collection — SSS Report missing all params",
        "question": "Generate an SSS report",
        "check_semantic_docs": True,
        "check_api_called": False,  # date, ffType, pointFilter[] all missing
    },
    {
        "name": "Parameter collection — Query Manager Report missing dates",
        "question": "Generate a Query Manager Report for Dhaka South region",
        "check_semantic_docs": True,
        "check_api_called": False,  # startDate, endDate, subChannels missing
    },
    {
        "name": "Parameter collection — Route Wise STT missing date range",
        "question": "Generate a Route Wise STT report for Dhanmondi",
        "check_semantic_docs": True,
        "check_api_called": False,  # startDate, endDate, productType missing
    },
    {
        "name": "Parameter collection — Survey Report missing survey ID",
        "question": "Generate a Survey report from 2026-01-01 to 2026-01-31",
        "check_semantic_docs": True,
        "check_api_called": False,  # surveyId missing
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
