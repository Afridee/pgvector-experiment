"""
API AGENT
=========
Hybrid API-calling + RAG agent for answering questions and generating reports.
"""

import json
import os
import threading
import contextvars
from datetime import date, timedelta
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
BASE_URL = os.getenv("BASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set (check your .env).")
if not CHECKPOINT_DB_URL:
    raise ValueError("CHECKPOINT_DB_URL is not set (check your .env).")
if not BASE_URL:
    raise ValueError("BASE_URL is not set (check your .env).")

# ----------------------------------------------------------------------------
# Per-request auth token context (set by ask_agent, read by api_call)
# ----------------------------------------------------------------------------
_auth_tokens: contextvars.ContextVar[Dict[str, str]] = contextvars.ContextVar(
    "_auth_tokens", default={}
)

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
            "Example: \"result = response.get('data', {{}}).get('user', {{}}).get('address')\". "
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
    # Inject auth headers from per-request ContextVar
    tokens = _auth_tokens.get()
    if tokens:
        headers = headers or {}
        if access_token := tokens.get("access_token"):
            headers.setdefault("Authorization", f"Bearer {access_token}")
        if refresh_token := tokens.get("refresh_token"):
            headers.setdefault("x-refresh-token", refresh_token)
        if validate_token := tokens.get("validate_token"):
            headers.setdefault("x-validate-token", validate_token)

    # Fallback: inject API_TOKEN from env if still no Authorization header
    if not (headers or {}).get("Authorization"):
        api_token = os.getenv("API_TOKEN")
        if api_token:
            headers = headers or {}
            headers["Authorization"] = f"Bearer {api_token}"

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
                json.dump(
                    {
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "body": data,
                    },
                    _f,
                    indent=2,
                    ensure_ascii=False,
                )

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
# System Prompt — date helpers (resolved once at agent initialisation)
# ----------------------------------------------------------------------------
_today = date.today()
_yesterday = _today - timedelta(days=1)
_this_week_start = _today - timedelta(days=_today.weekday())          # Monday
_last_week_start = _this_week_start - timedelta(weeks=1)
_last_week_end   = _this_week_start - timedelta(days=1)               # Sunday
_this_month_start = _today.replace(day=1)
_last_month_end   = _this_month_start - timedelta(days=1)
_last_month_start = _last_month_end.replace(day=1)
_this_year_start  = _today.replace(month=1, day=1)
_last_year_start  = _today.replace(year=_today.year - 1, month=1, day=1)
_last_year_end    = _today.replace(year=_today.year - 1, month=12, day=31)

# ----------------------------------------------------------------------------
# System Prompt
# ----------------------------------------------------------------------------
system_prompt = f"""
You are a report assistant that answers questions by calling APIs.

## Workflow
1. **Search docs**: Call semantic_search_tool() to find endpoint docs (params, payload, auth, response shape). Retry with different queries if needed.
2. **Resolve params**: Check retrieved docs for all required params. If the user gave a name but the API needs an ID, search the knowledge base for lookup tables before asking. Only ask the user when no mapping exists. Ask for ALL missing params in one message.
3. **Call API**: Build the request exactly per the docs, then call api_call().
   - Call semantic_search_tool() if necessary to get an idea of the responce shape of the endpoint from the docs to write the extraction_script or response_fields before calling api_call.
   - Use extraction_script (receives `response`, must assign `result`) for nested/conditional extraction. Use response_fields only for simple top-level keys.
   - **Pagination (CRITICAL):** If response is a list or one of response's field is a list, always set list_limit=20 and list_offset=0 when any array exists in the response (top-level or nested).
     - When has_more is true and the user asks for more, call the same API again with list_offset incremented by 20.
4. **Present**: Tables for lists, bullets for metrics. Show download links prominently. For paged results show "Showing X–Y of N" and offer to load more. Explain errors in plain language.

## Dates
Today: {_today}. Resolve relative dates silently (YYYY-MM-DD).
today={_today} | yesterday={_yesterday} | this week={_this_week_start}–{_today} | last week={_last_week_start}–{_last_week_end} | this month={_this_month_start}–{_today} | last month={_last_month_start}–{_last_month_end} | this year={_this_year_start}–{_today} | last year={_last_year_start}–{_last_year_end}
"last N days/weeks/months" — compute start yourself. Use single `date` or `startDate`/`endDate` as the API requires.

## Base URL: {BASE_URL}

## Rules
- All endpoint URLs, params, and payload fields MUST come from knowledge chunks — never guess.
- Never call api_call() until all required params are collected.
- Prefer extraction_script over response_fields; large JSON is not stored in conversation memory.
- Never expose raw API responses, endpoint URLs, HTTP methods, params, payload shapes, or response schemas to the user.
- If no user input is needed (e.g. "list all venues"), call the API immediately — don't describe the endpoint or ask for confirmation.
- If the knowledge base doesn't cover the request, say so and ask for clarification.
- Auth tokens come from env vars — never ask the user for them.
- Don't auto-fetch all pages unless the user explicitly asks.
- Be concise. Always show download links when present.
- **Pagination is mandatory**: Always apply pagination settings (list_limit and list_offset) when dealing with list responses. Never ignore this step.
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


def ask_agent(question: str, thread_id: str, auth_tokens: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Public entry point called by the Streamlit app (and tests).

    Args:
        question:    The user's message.
        thread_id:   LangGraph conversation thread ID.
        auth_tokens: Dict with keys: access_token, refresh_token, validate_token.
                     If provided, injected into every api_call made during this turn.

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

    # Set tokens for this request; reset when done (ContextVar is per-thread/task)
    ctx_token = _auth_tokens.set(auth_tokens or {})
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"configurable": {"thread_id": thread_id}},
        )
    finally:
        _auth_tokens.reset(ctx_token)

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
