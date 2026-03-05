"""
API AGENT
=========
Hybrid API-calling + RAG agent for answering questions and generating reports.
"""

import os
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
_CHECKPOINTER = None     # entered saver instance


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
            if len(preview) > 400:
                preview = preview[:400].rstrip() + "..."

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
        default="GET",
        description="HTTP method: GET, POST, PUT, DELETE, PATCH",
    )
    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON payload / request body (for POST, PUT, PATCH)",
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Custom HTTP headers, e.g. {'Authorization': 'Bearer token'}",
    )
    params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="URL query parameters (for GET requests)",
    )


@tool(args_schema=ApiInput)
def api_call(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> str:
    """Make an HTTP API call and return the response.
    Use this ONLY after you have collected all required parameters from the user.
    Returns the JSON response (or raw text) on success, or an error message on failure.
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
            return f"Success ({response.status_code}): {data}"
        except ValueError:
            return f"Success ({response.status_code}): {response.text}"

    except requests.exceptions.HTTPError as e:
        # Include response body for better error context
        body = ""
        if e.response is not None:
            try:
                body = e.response.json()
            except ValueError:
                body = e.response.text
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
    connection=DATABASE_URL,
    collection_name=VECTOR_COLLECTION,
    embeddings=embeddings,
)
print("   ✓ Vector database connected")

llm = init_chat_model("gpt-4o", model_provider="openai", temperature=0)

all_tools = [semantic_search_tool, api_call]

# ----------------------------------------------------------------------------
# System Prompt
# ----------------------------------------------------------------------------
system_prompt = """
You are a helpful report assistant that answers user questions by calling APIs.

## Your workflow

### Step 1 — Understand the request
When a user asks for a report or data, first call semantic_search_tool() with a
relevant query to find the matching API documentation from the knowledge base.
- The chunks describe available endpoints, required/optional parameters,
  payload structure, authentication, and response shapes.
- If the first search doesn't return enough context, search again with a
  different or more specific query.

### Step 2 — Identify missing parameters
Read the retrieved API documentation carefully. Identify every required parameter
that the user has NOT yet provided.

Ask the user for ALL missing required parameters in a single, friendly message.
List each missing piece clearly. Do NOT call the API until you have everything.

### Step 3 — Confirm and call
Once you have all required parameters, construct the correct request
(URL, method, headers, payload / query params) exactly as documented in the
knowledge chunks, then call api_call().

### Step 4 — Present the results
Present the API response in a clear, readable format:
- Use a table for tabular / list data.
- Use bullet points or a summary for key metrics.
- If the response contains a download URL or file link, display it prominently
  as a clickable link so the user can download their report.
- If the response indicates an error, explain it in plain language and suggest
  what the user can do next.

## Hard rules
- NEVER guess an endpoint URL, parameter name, or payload field.
  Everything must come from the knowledge chunks.
- NEVER call api_call() before all required parameters are collected.
- NEVER expose raw API responses unless the user explicitly asks for them.
- If the knowledge base does not cover what the user is asking, say so clearly
  and ask for clarification.
- Auth tokens/keys come from environment variables — never ask the user for them.

## Output
Respond naturally in plain language. Be concise but complete.
If a download link is present in the response, always show it.
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