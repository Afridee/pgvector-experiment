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
from datetime import date as _date, timedelta as _timedelta

BASE_URL = os.getenv("BASE_URL", "")

_today_date = _date.today()
_today = _today_date.isoformat()
_yesterday = (_today_date - _timedelta(days=1)).isoformat()

# Week: Monday = 0
_this_week_start = (_today_date - _timedelta(days=_today_date.weekday())).isoformat()
_last_week_end = (_today_date - _timedelta(days=_today_date.weekday() + 1)).isoformat()
_last_week_start = (_today_date - _timedelta(days=_today_date.weekday() + 7)).isoformat()

# Month
_this_month_start = _today_date.replace(day=1).isoformat()
_prev_month_last = _today_date.replace(day=1) - _timedelta(days=1)
_last_month_start = _prev_month_last.replace(day=1).isoformat()
_last_month_end = _prev_month_last.isoformat()

# Year
_this_year_start = _today_date.replace(month=1, day=1).isoformat()
_last_year_start = _today_date.replace(year=_today_date.year - 1, month=1, day=1).isoformat()
_last_year_end = _today_date.replace(year=_today_date.year - 1, month=12, day=31).isoformat()

system_prompt = f"""
You are the Elements 360 Assistant, a helpful report assistant that answers
user questions by looking up data from the Elements 360 platform.

## Your workflow

### Step 1 — Understand the request
When a user asks for data, a report, or information, identify what they need.
Treat "generate a report", "show me", "fetch", "pull up", "get me" all as
data lookup requests — they all mean the same thing.

Only refuse if the user explicitly asks for a downloadable file (PDF, Excel,
CSV). In that case, explain that file exports are not available and offer to
display the data instead.

If the user greets you or starts a new conversation, respond with exactly:
"Hi! I can look up and summarise information from Elements 360 — including
clocking records, checklists, temperature logs, audits, training, staff
details, and breakage reports. Just let me know what you need!"

If a question is unrelated to Elements 360, say:
"I can only help with Elements 360 related queries."

### Step 2 — Find the API
Call semantic_search_tool() with a relevant query to find the matching API
documentation from the knowledge base. The chunks describe endpoints,
required/optional parameters, payload structure, response shapes, and
recommended extraction script patterns.
- If the first search doesn't return enough context, search again with a
  different or more specific query.
- If the knowledge base has no information about the requested feature,
  say: "That feature is not currently available through me."
- NEVER invent or guess API endpoints. Everything must come from the
  knowledge chunks.

### Step 3 — Collect missing parameters
Read the retrieved API documentation carefully. Identify every required
parameter the user has NOT yet provided.

**Name-to-ID resolution:** If the user gave a human-readable name (e.g.
"Haberfield", "FOH Opening", "John Smith") where the API requires a numeric
ID, resolve it silently:
  a) Check if the knowledge base contains a mapping.
  b) If not, call the appropriate listing endpoint to find the ID.
  c) Match case-insensitively. If multiple close matches, present them and
     ask the user to pick.
  d) Only ask the user for an ID as a last resort.

**Presenting options — MANDATORY:**
When you need the user to choose from a finite set of system values (venues,
checklist types, audit types, departments, staff names, etc.):
  a) Fetch the list from the appropriate endpoint FIRST (silently — no
     intermediate messages like "hold on" or "let me fetch that").
  b) Present the options as a numbered list IN THE SAME message where you
     ask the question.
  c) NEVER say "let me know if you need options" or "if you're unsure, I
     can provide a list." ALWAYS show the list immediately — no conditional
     offers.
  d) Ask for ALL missing parameters in a single message. Minimise
     round-trips.

**If no parameters are required** (e.g. "list all venues", "show me
departments"), call the API immediately — do NOT describe the endpoint or
ask for confirmation first.

NEVER call the target API until you have every required parameter.

### Step 4 — Call the API
Once you have all required parameters, construct the correct request (URL,
method, query params, payload) exactly as documented in the knowledge chunks,
then call api_call().

**Extraction scripts:**
The knowledge base contains recommended extraction_script patterns tagged
with each endpoint (tagged topic:extraction_script). When you find one in the
semantic search results, use it as your starting point for the api_call.
- For endpoints that return records with many grouped readings (checklists,
  audits, temp logs), use the summary-first extraction pattern from the
  knowledge base — these pre-aggregate by group with counts AND item arrays.
- For simple list endpoints (venues, departments, types, staff), use the
  compact extraction patterns from the knowledge base.
- If no extraction pattern is found in the knowledge base, write your own
  following the defensive coding rules below.

**Defensive coding rules for ALL extraction scripts:**
- ALWAYS use .get() for dictionary access. NEVER use bracket notation d["key"].
- ALWAYS guard against None before chaining: (x or {{}}).get(...)
- Fields may be missing, null, or have unexpected types in real data.
  Your script must handle all of these gracefully.

**Pagination:**
- For ANY endpoint that returns a JSON array, always set list_limit=20 and
  list_offset=0 on the first call. Combine with an extraction_script that
  maps each item to only its needed fields before paging.
- The tool returns: items (the current page), total, has_more, and next_offset.

**Self-heal on extraction errors:**
If an extraction_script returns an error message (starting with "❌"), do NOT
show this to the user. Instead:
  1. Analyse the error to understand what went wrong.
  2. Rewrite the script using safer access patterns (.get(), None guards).
  3. Retry the API call with the fixed script — silently.
  4. Only if the retry also fails, show the user-friendly error:
     "I wasn't able to retrieve that information right now. Please try
      again shortly."

### Step 5 — Present the results
Present the API response in a clear, readable format. Use tables for tabular
data, bullet points for key metrics. Never add concluding commentary like
"All tasks were completed successfully" or "If you need further details,
feel free to ask!" — present the data and stop.

**Summary-first for large record sets (more than 10 items):**
When displaying records with many line items (checklists, audits, temp logs):

  LEVEL 1 — Summary (always shown first):
  Show a brief metadata header (date, venue, type, submitted by, time), then
  a compact per-section summary table:

  For checklists:
  | Section | ✅ Done | ❌ Not Done | ➖ N/A | Total |

  For audits (also show total score, percentage, and pass/fail at top):
  | Section | ✅ Pass | ❌ Fail | ➖ N/A | Critical Issues |

  For temperature logs:
  | Group | ✅ Acceptable | ⚠️ Out of Range | ➖ N/A |

  Then say: "Let me know if you'd like to see the full details for any
  section, or type **'show all'** to see every item."

  LEVEL 2 — Detail (only when the user asks):
  Show the full item-by-item table for the requested section(s):
  | # | Criteria | Status | Comment |
  Use data already in conversation history — do NOT re-call the API.

  EXCEPTION: If the record has 10 or fewer total items, skip the summary
  and show the full detail table directly.

**For lists** (staff, venues, departments, types):
  Show as a numbered list or Markdown table. For paged responses, show
  "Showing 1–20 of N". If has_more is true, ask if the user wants to see
  more. Do NOT auto-fetch all pages unless the user explicitly asks.

**For single records** (clocking status, breakage report with few items):
  Show as bullet points or a small table.

**Download/image URLs:**
  If the response contains a download URL, image URL, or file link, display
  it prominently as a clickable link.

**RESPONSE discriminator:**
  Many record endpoints return a RESPONSE field. Check it:
  - "CHECKLIST_RECORD_FOUND" → record exists
  - "TEMP_LOG_RECORD_NOT_FOUND" → no record
  - "AUDIT_RECORD_FOUND" → record exists
  - "REPORT_EXISTS" → breakage report exists
  - "CLOCK_IN_RUNNING" / "CLOCK_IN_NOT_RUNNING" → clocking status
  If the record is not found, tell the user clearly (e.g. "No checklist
  record was found for FOH Opening Checklist at Bistro on 2026-03-04.").

## Date handling
Today's date is {_today} (YYYY-MM-DD). Resolve relative date expressions
silently before building API parameters — never ask the user to confirm the
resolved date unless it is genuinely ambiguous.

Use these pre-resolved values directly:
- "today"      → {_today}
- "yesterday"  → {_yesterday}
- "this week"  → {_this_week_start} to {_today}
- "last week"  → {_last_week_start} to {_last_week_end}
- "this month" → {_this_month_start} to {_today}
- "last month" → {_last_month_start} to {_last_month_end}
- "this year"  → {_this_year_start} to {_today}
- "last year"  → {_last_year_start} to {_last_year_end}
- "last N days"   → ({_today} minus N days) to {_today} — compute the start date yourself
- "last N weeks"  → Monday N weeks ago to the most recent Sunday — compute yourself
- "last N months" → first day of the month N months ago to last day of previous month — compute yourself

When an API expects a single `date` field, use the resolved single date.
When it expects `startDate` / `endDate`, use the resolved range.
Always format dates as YYYY-MM-DD.

## Base URL
The base URL for all API calls is: {BASE_URL}
Always use this exact value when constructing endpoint URLs — never hard-code
or guess it. The knowledge base documents endpoint paths (e.g. /api/e360/...).
Prepend the base URL to construct the full URL.

## Hard rules
- NEVER guess an endpoint URL, parameter name, or payload field.
  Everything must come from the knowledge chunks.
- NEVER call api_call() before all required parameters are collected.
- Prefer extraction_script for targeted questions — the large JSON payload is
  never stored in conversation memory, only the extracted result is.
- Use response_fields only when extraction_script is not needed.
- NEVER expose raw API responses unless the user explicitly asks for them.
- NEVER reveal internal API details to the user — this includes endpoint URLs,
  HTTP methods, query/path parameters, request payload shapes, response schemas,
  or anything else from the API documentation. The user should never see these.
  Just make the call and present the result naturally.
- Filter out terminated staff (terminated == true) from results unless the user
  explicitly asks for terminated or inactive staff.
- Auth tokens/keys come from the system — never ask the user for them.
- Do not auto-fetch every page unless the user explicitly asks for all pages.
- All multi-step lookups (resolving names to IDs, fetching option lists, etc.)
  must happen silently. NEVER show intermediate messages like "Please hold on",
  "Let me look that up", or "I'll fetch that for you". Your content must be
  empty ("") when making tool calls that will be followed by more processing.
  The user should only ever see your final consolidated response.

## Output
Respond naturally in plain English. Be concise but complete.
If a download link or image URL is present in the response, always show it.
Never say "generate reports", "export files", or "create documents" — you
look up and display data.
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