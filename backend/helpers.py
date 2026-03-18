"""
Pure utility functions used by the API-call tool and the ask_agent response builder.
"""

import json
import threading
from typing import Any, Dict, List

from backend.config import (EXTRACTION_TIMEOUT_SECS,
                            MAX_FIELD_MATCHES_PER_TARGET,
                            MAX_TOOL_OUTPUT_CHARS)

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


def run_extraction_script(data: Any, script: str) -> str:
    """
    Execute a sandboxed Python snippet against the API response.

    Contract:
      - Input variable : ``response``  (the parsed JSON — dict or list)
      - Output variable: ``result``    (must be assigned by the script)
      - No imports, no file I/O, no network calls — only safe builtins.
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


def truncate_text(value: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(value) <= max_chars:
        return value
    return (
        value[:max_chars].rstrip() + f" ... [truncated {len(value) - max_chars} chars]"
    )


def _normalize_token(value: str) -> str:
    return value.replace("-", "").replace("_", "").replace(" ", "").lower()


def _path_tokens(path: str) -> List[str]:
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


def extract_response_fields(payload: Any, targets: List[str]) -> Dict[str, Any]:
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


def paginate_result(items: List[Any], offset: int, limit: int) -> Dict[str, Any]:
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


def serialize_docs(docs: List[Any]) -> List[Dict[str, Any]]:
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
