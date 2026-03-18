"""
API AGENT — Public entry points.

Exposes get_agent() and ask_agent() used by the Streamlit app.
"""

from typing import Any, Dict, List, Optional

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver

import backend.config as _cfg
from backend.graph import graph_builder
from backend.helpers import serialize_docs


def get_agent():
    """
    Streamlit-safe singleton:
    - keeps the PostgresSaver context open for the lifetime of the process
    - compiles the LangGraph once with the checkpointer
    """
    if _cfg.agent_instance is not None:
        return _cfg.agent_instance

    _cfg.checkpointer_cm = PostgresSaver.from_conn_string(_cfg.CHECKPOINT_DB_URL)
    _cfg.checkpointer = _cfg.checkpointer_cm.__enter__()

    if not isinstance(_cfg.checkpointer, BaseCheckpointSaver):
        raise TypeError(f"Expected BaseCheckpointSaver, got {type(_cfg.checkpointer)}")

    _cfg.checkpointer.setup()

    _cfg.agent_instance = graph_builder.compile(checkpointer=_cfg.checkpointer)
    return _cfg.agent_instance


def ask_agent(
    question: str, thread_id: str, auth_tokens: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Public entry point called by the Streamlit app (and tests).

    Args:
        question:    The user's message.
        thread_id:   LangGraph conversation thread ID.
        auth_tokens: Dict with keys: access_token, refresh_token, validate_token.
                     If provided, injected into every api_call made during this turn.

    Returns:
        {
            "answer":   str,
            "artifacts": {
                "semantic_search_docs": [...],
                "api_responses": [...],
            },
            "raw": ...
        }
    """
    agent = get_agent()

    ctx_token = _cfg.auth_tokens.set(auth_tokens or {})
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"configurable": {"thread_id": thread_id}},
        )
    finally:
        _cfg.auth_tokens.reset(ctx_token)

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

        if tool_name == "APIInput" and content:
            api_responses.append(str(content))

    if semantic_docs:
        artifacts["semantic_search_docs"] = serialize_docs(semantic_docs)
    if api_responses:
        artifacts["api_responses"] = api_responses

    return {"answer": answer, "artifacts": artifacts, "raw": result}
