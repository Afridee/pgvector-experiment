"""
Shared configuration: environment variables, constants, and per-request state.
"""

import contextvars
import os
from typing import Dict

from dotenv import load_dotenv

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

# Per-request auth token context (set by ask_agent, read by api_call_tool)
auth_tokens: contextvars.ContextVar[Dict[str, str]] = contextvars.ContextVar(
    "auth_tokens", default={}
)

# Singleton agent + checkpointer (mutated by agent.get_agent)
agent_instance = None
checkpointer_cm = None
checkpointer = None

MAX_TOOL_OUTPUT_CHARS = int(os.getenv("MAX_TOOL_OUTPUT_CHARS", "12000"))
MAX_FIELD_MATCHES_PER_TARGET = int(os.getenv("MAX_FIELD_MATCHES_PER_TARGET", "5"))
EXTRACTION_TIMEOUT_SECS = int(os.getenv("EXTRACTION_TIMEOUT_SECS", "5"))
