"""
Tool definitions: semantic search (RAG) and API call execution.
"""

import json
import os
from typing import Any, Dict, List, Optional

import requests
from langchain.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from pydantic import BaseModel, Field

from backend.config import DATABASE_URL, VECTOR_COLLECTION, auth_tokens
from backend.helpers import (extract_response_fields, run_extraction_script,
                             truncate_text)

# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------
print("🔗 Connecting to vector database...")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = PGVector(
    connection=DATABASE_URL, collection_name=VECTOR_COLLECTION, embeddings=embeddings,
)
print("   ✓ Vector database connected")


# ---------------------------------------------------------------------------
# Signal tool — tells the graph to route to the formatter node
# ---------------------------------------------------------------------------
@tool
def ready_to_format() -> str:
    """Call this ONLY after the final API call whose response should be
    presented to the user. Do NOT call after intermediate lookups like
    fetching types, venues, or IDs."""
    return "Routing to formatter."


# ---------------------------------------------------------------------------
# Semantic search tool
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# API call tool
# ---------------------------------------------------------------------------
class APIInput(BaseModel):
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


@tool("APIInput", args_schema=APIInput)
def api_call_tool(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    response_fields: Optional[List[str]] = None,
    extraction_script: Optional[str] = None,
) -> str:
    """Make an HTTP API call and return the response.
    Use this ONLY after you have collected all required parameters from the user.
    Returns JSON response (or raw text) on success, or an error message on failure.
    If response_fields is provided, only matching fields/paths are returned from JSON.
    If the response contains a download URL or file URL, preserve it so it can be
    shown to the user.
    """
    tokens = auth_tokens.get()
    if tokens:
        headers = headers or {}
        if access_token := tokens.get("access_token"):
            headers.setdefault("Authorization", f"Bearer {access_token}")
        if refresh_token := tokens.get("refresh_token"):
            headers.setdefault("x-refresh-token", refresh_token)
        if validate_token := tokens.get("validate_token"):
            headers.setdefault("x-validate-token", validate_token)

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

            if extraction_script:
                extracted = run_extraction_script(data, extraction_script)
                return f"Success ({response.status_code}) [extracted]: {truncate_text(extracted)}"

            if response_fields:
                filtered = extract_response_fields(data, response_fields)
                filtered["status_code"] = response.status_code
                if isinstance(data, dict):
                    filtered["top_level_keys"] = sorted(data.keys())
                serialized = json.dumps(filtered, ensure_ascii=True, default=str)
                return f"Success ({response.status_code}) [filtered]: {truncate_text(serialized)}"

            serialized = json.dumps(data, ensure_ascii=True, default=str)
            return f"Success ({response.status_code}): {truncate_text(serialized)}"
        except ValueError:
            return f"Success ({response.status_code}): {truncate_text(response.text)}"

    except requests.exceptions.HTTPError as e:
        body = ""
        if e.response is not None:
            try:
                body = e.response.json()
                body = truncate_text(json.dumps(body, ensure_ascii=True, default=str))
            except ValueError:
                body = truncate_text(e.response.text)
        return (
            f"HTTP Error ({getattr(e.response, 'status_code', 'Unknown')}): "
            f"{str(e)} | Response body: {body}"
        )
    except requests.exceptions.RequestException as e:
        return f"Request Error: {str(e)}"
