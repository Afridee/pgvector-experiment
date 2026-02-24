"""
Streamlit Chat App for QMR Database + Knowledge Agent

Assumes you already expose:
    from backend.core import ask_database

Where ask_database(question: str) -> str (or dict) calls the LangChain agent.
"""

import json
import os

import streamlit as st

# Import your existing function (must be importable)
from backend.agent import ask_database

st.set_page_config(
    page_title="QMR Database + Knowledge Agent", page_icon="🧠", layout="wide",
)

st.title("QMR Database + Knowledge Agent")

with st.sidebar:
    st.header("Settings")
    st.caption("Uses your existing backend.core.ask_database()")

    show_debug = st.toggle("Show debug / raw response", value=False)
    st.divider()
    st.subheader("Environment")
    st.write(
        {
            "READONLY_DATABASE_URL set": bool(os.getenv("READONLY_DATABASE_URL")),
            "DATABASE_URL set": bool(os.getenv("DATABASE_URL")),
            "VECTOR_COLLECTION": os.getenv("VECTOR_COLLECTION", "qmr_knowledge_chunks"),
        }
    )
    st.divider()
    st.markdown(
        """
**Example questions**
- How is Memo calculated for SKU vs Total?
- What happens if today's date is within the requested date range?
- Which tables are used: monthly_order_cache_YYYY_MM vs daily_order_cache?
- What filters are supported (region/area/territory/subChannel/activeStatus)?
"""
    )

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Ask me about QMR report rules (Memo/STT, date splitting, filters) or run SQL-based questions.",
        }
    ]

# Render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
prompt = st.chat_input("Ask a question…")

if prompt:
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call backend
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                result = ask_database(prompt)

                # Your current ask_database returns a string.
                # But we also support a future enhancement: returning a dict with fields.
                if isinstance(result, dict):
                    answer = result.get("answer") or result.get("content") or ""
                    artifacts = result.get("artifacts")
                else:
                    answer = str(result)
                    artifacts = None

                st.markdown(answer)
                st.session_state.messages.append(
                    {"role": "assistant", "content": answer}
                )

                if show_debug:
                    st.divider()
                    st.subheader("Raw result")
                    try:
                        st.code(
                            json.dumps(result, indent=2, default=str), language="json"
                        )
                    except Exception:
                        st.write(result)

                # If you later return tool artifacts (e.g., the docs from semantic_search_tool),
                # you can display them here.
                # if artifacts:
                #     st.divider()
                #     st.subheader("Artifacts")
                #     st.write(artifacts)

            except Exception as e:
                err = f"Error: {e}"
                st.error(err)
                st.session_state.messages.append({"role": "assistant", "content": err})
