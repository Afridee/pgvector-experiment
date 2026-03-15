"""
API AGENT
=========
Hybrid API-calling + RAG agent for answering questions and generating reports.
"""

import json
import os
import threading
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import ToolMessage
from langchain.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = os.getenv("VECTOR_COLLECTION", "qmr_knowledge_chunks")
CHECKPOINT_DB_URL = os.getenv("CHECKPOINT_DB_URL", DATABASE_URL)

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set (check your .env).")
if not CHECKPOINT_DB_URL:
    raise ValueError("CHECKPOINT_DB_URL is not set (check your .env).")

# ----------------------------------------------------------------------------
# Globals (singleton agent + open context manager)
# ----------------------------------------------------------------------------
_AGENT = None
_CHECKPOINTER_CM = None  # context manager object
_CHECKPOINTER = None  # entered saver instance

MAX_TOOL_OUTPUT_CHARS = int(os.getenv("MAX_TOOL_OUTPUT_CHARS", "12000"))
MAX_FIELD_MATCHES_PER_TARGET = int(os.getenv("MAX_FIELD_MATCHES_PER_TARGET", "5"))
EXTRACTION_TIMEOUT_SECS = int(os.getenv("EXTRACTION_TIMEOUT_SECS", "5"))

# Builtins available inside extraction scripts — no imports, no file/network access.
_SCRIPT_BUILTINS: Dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "getattr": getattr,
    "hasattr": hasattr,
    "int": int,
    "isinstance": isinstance,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "range": range,
    "repr": repr,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    "None": None,
    "True": True,
    "False": False,
}


def _run_extraction_script(data: Any, script: str) -> str:
    """
    Execute a sandboxed Python snippet against the API response.

    Contract:
      - Input variable : `response`  (the parsed JSON — dict or list)
      - Output variable: `result`    (must be assigned by the script)
      - No imports, no file I/O, no network calls — only safe builtins above.
      - Hard timeout: EXTRACTION_TIMEOUT_SECS (default 5 s).

    Returns the JSON-serialised result, or an error string.
    """
    local_vars: Dict[str, Any] = {"response": data, "result": None}
    error_box: List[Any] = [None]

    def _exec() -> None:
        try:
            exec(
                compile(script, "<extraction_script>", "exec"),
                {"__builtins__": _SCRIPT_BUILTINS},
                local_vars,
            )
        except Exception as exc:  # noqa: BLE001
            error_box[0] = exc

    thread = threading.Thread(target=_exec, daemon=True)
    thread.start()
    thread.join(timeout=EXTRACTION_TIMEOUT_SECS)

    if thread.is_alive():
        return f"❌ Extraction script timed out after {EXTRACTION_TIMEOUT_SECS}s."
    if error_box[0]:
        return f"❌ Extraction script error: {error_box[0]}"

    result = local_vars.get("result")
    if result is None:
        return "❌ Extraction script did not assign to 'result'."

    try:
        return json.dumps(result, ensure_ascii=True, default=str)
    except Exception:  # noqa: BLE001
        return str(result)


def _truncate_text(value: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(value) <= max_chars:
        return value
    return (
        value[:max_chars].rstrip() + f" ... [truncated {len(value) - max_chars} chars]"
    )


def _normalize_token(value: str) -> str:
    return value.replace("-", "").replace("_", "").replace(" ", "").lower()


def _path_tokens(path: str) -> List[str]:
    # Example: users[0].profile.address.city -> [users, profile, address, city]
    tokens: List[str] = []
    current = []
    for ch in path:
        if ch in ".[]":
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _matches_target(target: str, key: str, full_path: str) -> bool:
    norm_target = _normalize_token(target)
    norm_key = _normalize_token(key)
    if norm_target == norm_key:
        return True

    # Allow dotted selectors, e.g. profile.address.city
    target_parts = [_normalize_token(p) for p in target.split(".") if p.strip()]
    if not target_parts:
        return False
    path_parts = [_normalize_token(p) for p in _path_tokens(full_path) if p.strip()]
    return (
        len(path_parts) >= len(target_parts)
        and path_parts[-len(target_parts) :] == target_parts
    )


def _collect_field_matches(
    payload: Any, target: str, path: str, out: List[Dict[str, Any]],
) -> None:
    if len(out) >= MAX_FIELD_MATCHES_PER_TARGET:
        return

    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{path}.{key}" if path else key
            if _matches_target(target, key, child_path):
                out.append({"field": target, "path": child_path, "value": value})
                if len(out) >= MAX_FIELD_MATCHES_PER_TARGET:
                    return
            _collect_field_matches(value, target, child_path, out)
            if len(out) >= MAX_FIELD_MATCHES_PER_TARGET:
                return
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            child_path = f"{path}[{idx}]" if path else f"[{idx}]"
            _collect_field_matches(item, target, child_path, out)
            if len(out) >= MAX_FIELD_MATCHES_PER_TARGET:
                return


def _extract_response_fields(payload: Any, targets: List[str]) -> Dict[str, Any]:
    requested = [t for t in (targets or []) if isinstance(t, str) and t.strip()]
    matches: List[Dict[str, Any]] = []
    missing: List[str] = []

    for target in requested:
        collected: List[Dict[str, Any]] = []
        _collect_field_matches(payload, target.strip(), "", collected)
        if collected:
            matches.extend(collected)
        else:
            missing.append(target)

    return {
        "requested_fields": requested,
        "matched_fields": matches,
        "missing_fields": missing,
    }


def _paginate_result(items: List[Any], offset: int, limit: int) -> Dict[str, Any]:
    total = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total
    return {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
    }


# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------


@tool(response_format="content_and_artifact")
def semantic_search_tool(query: str):
    """Search knowledge chunks by semantic similarity (RAG over pgvector).
    Use this to find API documentation, endpoint details, required parameters,
    payload structure, auth requirements, and response shapes.
    """
    try:
        docs = vectorstore.similarity_search(query, k=5)
        if not docs:
            return "No relevant knowledge found.", []

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

            results.append(
                f"{i}. {title}\n"
                f"   Tags: {', '.join(tags) if tags else 'N/A'}\n"
                f"   Source: {source_file} (chunk {chunk_index})\n"
                f"   Preview: {preview}"
            )

        return "\n\n".join(results), docs
    except Exception as e:
        return f"❌ Error in semantic_search_tool: {str(e)}", []


class ApiInput(BaseModel):
    """Schema for API calls."""

    url: str = Field(..., description="Full API endpoint URL")
    method: str = Field(
        default="GET", description="HTTP method: GET, POST, PUT, DELETE, PATCH",
    )
    payload: Optional[Dict[str, Any]] = Field(
        default=None, description="JSON payload / request body (for POST, PUT, PATCH)",
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Custom HTTP headers, e.g. {'Authorization': 'Bearer token'}",
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None, description="URL query parameters (for GET requests)",
    )
    response_fields: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional field names or dotted paths to extract from JSON response, "
            "e.g. ['address', 'profile.address.city', 'download_url']. "
            "Used for simple key/path matching. Ignored when extraction_script is set."
        ),
    )
    extraction_script: Optional[str] = Field(
        default=None,
        description=(
            "Optional Python snippet to run against the parsed JSON response. "
            "The script receives 'response' (the full parsed JSON) and MUST assign "
            "to 'result'. Only safe builtins are available — no imports. "
            "Example: \"result = response.get('data', {}).get('user', {}).get('address')\". "
            "Prefer this over response_fields for nested or conditional extraction."
        ),
    )
    list_offset: Optional[int] = Field(
        default=None,
        description=(
            "For list responses: zero-based index of the first item to return. "
            "Use with list_limit to page through results. Defaults to 0."
        ),
    )
    list_limit: Optional[int] = Field(
        default=None,
        description=(
            "For list responses: maximum number of items to return per page. "
            "Always set this (recommended: 20) when the response is a list of records."
        ),
    )


@tool(args_schema=ApiInput)
def api_call(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    response_fields: Optional[List[str]] = None,
    extraction_script: Optional[str] = None,
    list_offset: Optional[int] = None,
    list_limit: Optional[int] = None,
) -> str:
    """Make an HTTP API call and return the response.
    Use this ONLY after you have collected all required parameters from the user.
    Returns JSON response (or raw text) on success, or an error message on failure.
    If response_fields is provided, only matching fields/paths are returned from JSON.
    If the response contains a download URL or file URL, preserve it so it can be
    shown to the user.
    """
    # Inject auth token from env if the caller did not supply an Authorization header
    api_token = os.getenv("API_TOKEN")
    if api_token:
        headers = headers or {}
        headers.setdefault("Authorization", f"Bearer {api_token}")

    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            json=payload,
            headers=headers,
            params=params,
            timeout=60,
        )
        response.raise_for_status()

        # Try JSON first; fall back to raw text
        try:
            data = response.json()

            print(f"API call to {url} succeeded. Status code: {response.status_code}.")
            with open("api_response_debug.json", "w", encoding="utf-8") as _f:
                json.dump(data, _f, indent=2, ensure_ascii=False)

            # extraction_script takes priority — model-written Python snippet
            if extraction_script:
                extracted = _run_extraction_script(data, extraction_script)
                if list_limit is not None:
                    try:
                        extracted_data = json.loads(extracted)
                        if isinstance(extracted_data, list):
                            paged = _paginate_result(
                                extracted_data, list_offset or 0, list_limit
                            )
                            serialized = json.dumps(
                                paged, ensure_ascii=True, default=str
                            )
                            return f"Success ({response.status_code}) [extracted+paged]: {_truncate_text(serialized)}"
                    except (ValueError, TypeError):
                        pass
                return f"Success ({response.status_code}) [extracted]: {_truncate_text(extracted)}"

            # response_fields — simple key/path matching
            if response_fields:
                filtered = _extract_response_fields(data, response_fields)
                filtered["status_code"] = response.status_code
                if isinstance(data, dict):
                    filtered["top_level_keys"] = sorted(data.keys())
                serialized = json.dumps(filtered, ensure_ascii=True, default=str)
                return f"Success ({response.status_code}) [filtered]: {_truncate_text(serialized)}"

            # Client-side list pagination
            if list_limit is not None and isinstance(data, list):
                paged = _paginate_result(data, list_offset or 0, list_limit)
                serialized = json.dumps(paged, ensure_ascii=True, default=str)
                return f"Success ({response.status_code}) [paged]: {_truncate_text(serialized)}"

            serialized = json.dumps(data, ensure_ascii=True, default=str)
            return f"Success ({response.status_code}): {_truncate_text(serialized)}"
        except ValueError:
            return f"Success ({response.status_code}): {_truncate_text(response.text)}"

    except requests.exceptions.HTTPError as e:
        # Include response body for better error context
        body = ""
        if e.response is not None:
            try:
                body = e.response.json()
                body = _truncate_text(json.dumps(body, ensure_ascii=True, default=str))
            except ValueError:
                body = _truncate_text(e.response.text)
        return (
            f"HTTP Error ({getattr(e.response, 'status_code', 'Unknown')}): "
            f"{str(e)} | Response body: {body}"
        )
    except requests.exceptions.RequestException as e:
        return f"Request Error: {str(e)}"


# ----------------------------------------------------------------------------
# Vector store
# ----------------------------------------------------------------------------
print("🔗 Connecting to vector database...")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = PGVector(
    connection=DATABASE_URL, collection_name=VECTOR_COLLECTION, embeddings=embeddings,
)
print("   ✓ Vector database connected")

llm = init_chat_model("gpt-4o", model_provider="openai", temperature=0)

all_tools = [semantic_search_tool, api_call]

# ----------------------------------------------------------------------------
# System Prompt
# ----------------------------------------------------------------------------
from datetime import date as _date

_TODAY = _date.today().isoformat()  # e.g. "2026-03-15"

system_prompt = f"""
You are the **Elements 360 Assistant** — an AI helper for staff and HR
personnel on the Elements 360 platform. Today's date is {_TODAY}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE IDENTITY & TONE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Helpful, professional, concise.
- Plain English only. Respond ONLY in English.
- NEVER expose API endpoints, URLs, JSON structures, HTTP status codes, or
  any internal system details to the user.
- When something fails AND you cannot recover, say:
    "I wasn't able to retrieve that information right now. Please try again
     shortly."
  Never show raw errors, codes, or stack traces.
- NEVER say "generate reports", "export files", or "create documents".
  You look up and display data — that is all.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GREETING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When the conversation starts or the user greets you, respond with EXACTLY
this (do NOT alter the wording):

  "Hi! I can look up and summarise information from Elements 360 — including
   clocking records, checklists, temperature logs, audits, training, staff
   details, and breakage reports. Just let me know what you need!"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEHAVIOUR RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. **Strictly reactive.** Only answer what the user asks. Do not volunteer
   suggestions, recommendations, commentary, or summary judgments.
   Do NOT add concluding sentences like "All tasks were completed
   successfully" or "If you need further details, feel free to ask!"
   Just present the data and stop.

2. **Absolutely silent multi-step resolution.** When answering requires
   multiple lookups (e.g., resolving a venue name → ID, then fetching a
   record), chain ALL necessary tool calls silently. NEVER show ANY
   intermediate text to the user such as:
     - "Please hold on while I fetch..."
     - "Let me look that up..."
     - "I'll fetch the options for you..."
   The user should only ever see your FINAL consolidated response.
   If you need to make tool calls, make them WITHOUT any preceding
   message text. Your `content` field MUST be empty ("") when you are
   making tool calls that will be followed by more processing.

3. **ALWAYS present options when asking for a required parameter.**
   THIS IS MANDATORY — NOT OPTIONAL.
   When you need the user to choose from a finite set of system values
   (venues, checklist types, audit types, departments, staff names, etc.):
     a) Fetch the list from the appropriate endpoint FIRST (silently).
     b) Present the options as a numbered list IN THE SAME message where
        you ask the question.
     c) NEVER ask a bare question like "Which venue?" or say "let me know
        if you need help choosing." Always show the options immediately.

4. **Collect ALL required parameters before making a data lookup call.**
   Consult your knowledge base to determine what parameters an endpoint
   needs. If ANY required parameter is missing, ask the user for it
   (following rule 3) BEFORE making the call. NEVER make a call with
   missing parameters.

   Key parameter requirements:
   - Checklist record: date + venueId + typeId (ALL THREE required)
   - Temperature log record: date + venueId
   - Audit record: date + venueId + auditTypeId
   - Breakage report: date + venue name (string, not ID)
   - Clocking records: staffId + page
   - Clocking status: staffId
   - Training criteria: trainingSubjectId
   - Training subject: stationId + trainingType
   - Staff by department: departmentId

5. **Ask for multiple missing parameters in one message when possible.**
   If you need both venue and checklist type, fetch both option lists
   and ask for both in a single message. Minimise round-trips.

6. **Understand user intent generously.** When the user says "get me a
   checklist report", "show me the checklist", "fetch the checklist",
   "pull up the checklist", or "generate a checklist report", they ALL
   mean: look up and display a checklist record.
   ONLY refuse if the user explicitly asks for a downloadable file
   (PDF, Excel, CSV). In that case, explain file exports are not
   available and offer to display the information instead.

7. **Structured presentation.** ALWAYS present multi-item results using
   Markdown tables:

   For **checklists**: show a brief header, then a table:
   | # | Criteria | Status | Comment |
   Use ✅ Done, ❌ Not Done, ➖ N/A for the Status column.
   If the checklist has groups, add a **bold group header row** spanning
   the table before each section's criteria.

   For **temperature logs**: table with #, Item, Reading, Unit,
   Acceptable Range, Status (✅ / ⚠️ Out of Range / ➖ N/A), Comment.

   For **audits**: score summary at top (total, %, pass/fail), then
   table: #, Criteria, Critical, Points, Status, Comment.

   For **clocking records**: table: Date, Clock In, Clock Out, Duration,
   Approved, Break. Show weekly totals as a summary row.

   For **staff lists**: table: Name, Department, and relevant fields.

   For **breakage reports**: metadata header, then table: Item, Size,
   Qty, Unit Cost, Total Cost, Reason.

   Always include a brief metadata header before the table (submitted by,
   date, venue, etc.). Do NOT add commentary or judgments after the table.

8. **Filter terminated staff.** Exclude staff with terminated == true
   unless the user explicitly asks for terminated/inactive staff.

9. **Date handling.** "Today" = {_TODAY}. Compute "yesterday", "last
   Monday", etc. relative to today. Convert to YYYY-MM-DD for lookups.

10. **Name matching.** When the user refers to a staff member, venue,
    department, or type by name, resolve it by fetching the relevant list
    and matching case-insensitively. If multiple close matches exist,
    present them and ask the user to pick.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOL USAGE — MANDATORY EFFICIENCY RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Tool responses are truncated at a hard character limit. To avoid receiving
incomplete data, you MUST follow these rules on EVERY api_call:

A. **Always paginate lists.** For ANY endpoint that returns a JSON array,
   set list_limit (recommended: 20). Start with list_offset=0. If the
   response indicates has_more=true and you need more data, make follow-up
   calls with the next_offset value.

B. **Prefer extraction_script for complex queries.** When the response
   payload is large or deeply nested, write a Python extraction script
   that pulls out only the fields you need. The script receives the parsed
   JSON as `response` and must assign to `result`. Only safe builtins are
   available (no imports).

   CRITICAL — DEFENSIVE CODING RULES FOR EXTRACTION SCRIPTS:
   - ALWAYS use .get() for dictionary access, NEVER use bracket notation
     like d["key"]. Use d.get("key") or d.get("key", default) instead.
   - ALWAYS guard against None before chaining: use (x or {{}}).get(...)
   - ALWAYS wrap list comprehensions in try/except or pre-check with
     isinstance() when the data shape might vary.
   - Fields may be missing, null, or have unexpected types in real data.
     Your script must handle all of these gracefully.

   Standard extraction patterns (ALWAYS use these as your starting point):

   Venue list:
     result = [{{"id": v.get("id"), "name": v.get("venueName")}} for v in (response if isinstance(response, list) else [])]

   Checklist types:
     result = [{{"id": t.get("id"), "type": t.get("type")}} for t in (response if isinstance(response, list) else [])]

   Checklist readings:
     r = response.get("RESPONSE", "")
     record = response.get("RECORD", {{}})
     sb = record.get("submittedBy") or {{}}
     result = {{"found": r == "CHECKLIST_RECORD_FOUND",
                "submitted": record.get("submitted"),
                "submittedBy": (sb.get("firstName", "") + " " + sb.get("lastName", "")).strip(),
                "submissionDateTime": record.get("submissionDateTime"),
                "venue": (record.get("elementsVenue") or {{}}).get("venueName"),
                "checklistType": (record.get("checklistType") or {{}}).get("type"),
                "readings": [{{"criteria": (r2.get("checklistCriteria") or {{}}).get("name"),
                               "group": (r2.get("checklistCriteria") or {{}}).get("checklistGroup") and ((r2.get("checklistCriteria") or {{}}).get("checklistGroup") or {{}}).get("name"),
                               "checked": r2.get("checked"),
                               "na": r2.get("na"),
                               "comment": r2.get("comment")}}
                              for r2 in record.get("checklistReadings", [])]}}

   Staff names from enrolments:
     result = [{{"name": (e.get("givenNames", "") + " " + e.get("surname", "")).strip(),
                 "staffId": (e.get("staff") or {{}}).get("id"),
                 "dept": (e.get("staffDepartment") or {{}}).get("name")}}
                for e in (response if isinstance(response, list) else [])
                if not (e.get("staff") or {{}}).get("terminated", False)]

   Clocking record summaries:
     result = [{{"week": w.get("startDate", "") + " to " + w.get("endDate", ""),
                 "totalHours": w.get("totalWorkDurationInWeek"),
                 "approved": w.get("totalApprovedWorkDurationInWeek"),
                 "records": [{{"date": r2.get("date"),
                               "clockIn": r2.get("clockInTime"),
                               "clockOut": r2.get("clockOutTime"),
                               "duration": r2.get("workDuration"),
                               "approved": r2.get("recordApproved"),
                               "break": r2.get("breakTime")}}
                              for r2 in w.get("clockingRecords", [])]}}
                for w in (response if isinstance(response, list) else [])]

   Temperature log readings:
     r = response.get("RESPONSE", "")
     record = response.get("RECORD", {{}})
     sb = record.get("submittedBy") or {{}}
     result = {{"found": r == "TEMP_LOG_RECORD_FOUND",
                "submitted": record.get("submitted"),
                "submittedBy": (sb.get("firstName", "") + " " + sb.get("lastName", "")).strip(),
                "submissionDateTime": record.get("submissionDateTime"),
                "venue": (record.get("elementsVenue") or {{}}).get("venueName"),
                "readings": [{{"item": (r2.get("tempLogCriteria") or {{}}).get("name"),
                               "value": r2.get("recordedValue"),
                               "unit": (r2.get("tempLogCriteria") or {{}}).get("unitCode", ""),
                               "min": (r2.get("tempLogCriteria") or {{}}).get("acceptableLowerValue"),
                               "max": (r2.get("tempLogCriteria") or {{}}).get("acceptableUpperValue"),
                               "acceptable": r2.get("acceptable"),
                               "na": r2.get("na"),
                               "comment": r2.get("comment"),
                               "group": ((r2.get("tempLogCriteria") or {{}}).get("tempLogGroup") or {{}}).get("name")}}
                              for r2 in record.get("tempLogReadings", [])]}}

   Audit readings:
     r = response.get("RESPONSE", "")
     record = response.get("RECORD", {{}})
     aud = record.get("auditor") or {{}}
     result = {{"found": r == "AUDIT_RECORD_FOUND",
                "totalScore": record.get("totalScore"),
                "scorePercentage": record.get("scorePercentage"),
                "passed": record.get("auditPassed"),
                "auditor": (aud.get("firstName", "") + " " + aud.get("lastName", "")).strip(),
                "submissionDateTime": record.get("submissionDateTime"),
                "venue": (record.get("elementsVenue") or {{}}).get("venueName"),
                "auditType": (record.get("auditType") or {{}}).get("type"),
                "readings": [{{"criteria": (r2.get("auditCriteria") or {{}}).get("name"),
                               "critical": (r2.get("auditCriteria") or {{}}).get("critical", False),
                               "points": (r2.get("auditCriteria") or {{}}).get("allocatedPoint"),
                               "checked": r2.get("checked"),
                               "na": r2.get("na"),
                               "comment": r2.get("comment"),
                               "group": ((r2.get("auditCriteria") or {{}}).get("auditGroup") or {{}}).get("name")}}
                              for r2 in record.get("auditReadings", [])]}}

   Breakage report:
     r = response.get("RESPONSE", "")
     rpt = response.get("REPORT", {{}})
     sb = rpt.get("submittedByStaff") or {{}}
     result = {{"found": r == "REPORT_EXISTS",
                "venue": rpt.get("venue"),
                "date": rpt.get("date"),
                "day": rpt.get("day"),
                "finalized": rpt.get("finalized"),
                "netSales": rpt.get("netSales"),
                "totalCost": rpt.get("totalBreakageCost"),
                "totalPct": rpt.get("totalBreakagePercentage"),
                "submittedBy": (sb.get("firstName", "") + " " + sb.get("lastName", "")).strip(),
                "details": [{{"item": (d.get("glasswareItem") or {{}}).get("name"),
                              "size": (d.get("glasswareItem") or {{}}).get("size"),
                              "qty": d.get("qty"),
                              "unitCost": (d.get("glasswareItem") or {{}}).get("unitCost"),
                              "totalCost": d.get("totalCost"),
                              "reason": d.get("reason")}}
                             for d in rpt.get("breakageDetails", [])]}}

C. **Use response_fields for simple targeted lookups.** When you only need
   a few specific fields, use response_fields with dotted paths.

D. **Combine extraction_script with list_limit.** When extracting from a
   list, also set list_limit.

E. **Never fetch all data "just in case."** Only request what you need.

F. **Check the RESPONSE / found discriminator.** After extraction, check
   the "found" field in the result. If it is false or the record is
   empty, tell the user clearly, e.g.:
     "No checklist record was found for FOH Opening Checklist at Bistro
      on 2026-03-04."

G. **Self-heal extraction errors.** If an extraction_script returns an
   error message (starting with "❌"), do NOT show this to the user.
   Instead:
     1. Analyse the error to understand what went wrong.
     2. Rewrite the script using safer access patterns (.get() etc.).
     3. Retry the API call with the fixed script.
     4. Only if the retry also fails, show the user-friendly error message.
   The user must NEVER see extraction script errors or be asked to retry
   something that you can fix yourself.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KNOWLEDGE BASE (semantic_search_tool)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ALWAYS use semantic_search_tool to find the correct endpoint, required
  parameters, and response structure BEFORE making any api_call.
- If the knowledge base has no information about a requested feature,
  say: "That feature is not currently available through me."
- NEVER invent or guess API endpoints.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOMAIN MODULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The platform covers:
- **Clocking** — clock-in/out records, live status, site locations
- **Enrolment** — staff profiles, departments, full enrolment data
- **Checklists** — checklists by type, venue, and date with criteria
- **Temperature Logs** — daily temp readings by venue with acceptable ranges
- **Audits** — audit records, types, criteria, scores, pass/fail
- **Training** — training subjects, stations, criteria
- **Breakage Reports** — glassware/breakage by venue and date

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOUNDARIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- You CANNOT export or download files (PDF, Excel, CSV). If asked, offer
  to display the data instead.
- You CANNOT access features outside your knowledge base.
- If a question is unrelated to Elements 360, say:
  "I can only help with Elements 360 related queries."
""".strip()


# ----------------------------------------------------------------------------
# Agent singleton
# ----------------------------------------------------------------------------
def get_agent():
    """
    Streamlit-safe singleton:
    - keeps the PostgresSaver context open for the lifetime of the process
    - creates the agent once
    """
    global _AGENT, _CHECKPOINTER_CM, _CHECKPOINTER

    if _AGENT is not None:
        return _AGENT

    _CHECKPOINTER_CM = PostgresSaver.from_conn_string(CHECKPOINT_DB_URL)
    _CHECKPOINTER = _CHECKPOINTER_CM.__enter__()

    if not isinstance(_CHECKPOINTER, BaseCheckpointSaver):
        raise TypeError(f"Expected BaseCheckpointSaver, got {type(_CHECKPOINTER)}")

    _CHECKPOINTER.setup()

    _AGENT = create_agent(
        model=llm,
        tools=all_tools,
        system_prompt=system_prompt,
        checkpointer=_CHECKPOINTER,
    )
    return _AGENT


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _serialize_docs(docs: List[Any]) -> List[Dict[str, Any]]:
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
                "preview": content[:800],
                "metadata": meta,
            }
        )
    return serialized


def ask_agent(question: str, thread_id: str) -> Dict[str, Any]:
    """
    Public entry point called by the Streamlit app (and tests).

    Returns:
        {
            "answer":   str,               # final assistant message
            "artifacts": {                 # optional tool outputs
                "semantic_search_docs": [...],
                "api_responses": [...],
            },
            "raw": ...                     # full LangGraph result (for debug)
        }
    """
    agent = get_agent()

    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config={"configurable": {"thread_id": thread_id}},
    )

    answer = result["messages"][-1].content

    artifacts: Dict[str, Any] = {}
    semantic_docs: List[Any] = []
    api_responses: List[str] = []

    for message in result.get("messages", []):
        if not isinstance(message, ToolMessage):
            continue

        tool_name = (
            getattr(message, "name", None)
            or getattr(message, "tool", None)
            or getattr(message, "tool_name", None)
        )
        artifact = getattr(message, "artifact", None)
        content = getattr(message, "content", None)

        if (
            tool_name == "semantic_search_tool"
            and isinstance(artifact, list)
            and artifact
        ):
            semantic_docs.extend(artifact)

        if tool_name == "api_call" and content:
            api_responses.append(str(content))

    if semantic_docs:
        artifacts["semantic_search_docs"] = _serialize_docs(semantic_docs)
    if api_responses:
        artifacts["api_responses"] = api_responses

    return {"answer": answer, "artifacts": artifacts, "raw": result}