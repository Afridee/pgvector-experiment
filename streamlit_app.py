"""
Streamlit Chat App — API + Knowledge Agent

Calls ask_agent(question, thread_id) from backend.agent.
"""

import json
import os
import uuid

import requests
import streamlit as st

from backend.agent import ask_agent


# ----------------------------------------------------------------------------
# Helper — extract and render download links from API response strings
# ----------------------------------------------------------------------------
def _extract_and_show_download_link(api_response_str: str) -> None:
    """
    If the API response contains a URL that looks like a file download
    (common keys: download_url, file_url, report_url, url), render it
    as a visible download link in the Streamlit UI.
    """
    import re

    # Try to parse JSON out of the success string "Success (200): {...}"
    match = re.search(r"Success \(\d+\):\s*(\{.*\}|\[.*\])", api_response_str, re.S)
    if not match:
        return

    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return

    # Flatten one level if it's a list
    if isinstance(data, list) and data:
        data = data[0]

    if not isinstance(data, dict):
        return

    # Common keys that APIs use for downloadable file links
    link_keys = ["download_url", "file_url", "report_url", "url", "link", "file_link"]
    for key in link_keys:
        url = data.get(key)
        if url and isinstance(url, str) and url.startswith("http"):
            st.divider()
            st.markdown(f"📥 **Download your report:** [Click here to download]({url})")
            break


st.set_page_config(
    page_title="Report Assistant", page_icon="📊", layout="wide",
)

st.title("Report Assistant")

# ----------------------------------------------------------------------------
# Auth — Login gate
# Tokens are stored in session_state after a successful login.
# ----------------------------------------------------------------------------
def _do_login(username: str, password: str) -> dict:
    """
    Call your login endpoint and return the three auth tokens.
    Adjust the URL and payload shape to match your actual login API.
    """
    base_url = os.getenv("BASE_URL", "")
    resp = requests.post(
        f"{base_url}/auth/login",
        json={"identifier": username, "password": password, "platform": "prism"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return {
        "access_token": data["accessToken"],
        "refresh_token": data["refreshToken"],
        "validate_token": data["validateToken"],
    }


if "auth_tokens" not in st.session_state:
    st.session_state.auth_tokens = None

if st.session_state.auth_tokens is None:
    st.subheader("Please log in")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if submitted:
        if not username or not password:
            st.error("Please enter both username and password.")
        else:
            try:
                tokens = _do_login(username, password)
                st.session_state.auth_tokens = tokens
                st.rerun()
            except requests.exceptions.HTTPError as e:
                st.error(f"Login failed: {e.response.status_code} — {e.response.text}")
            except Exception as e:
                st.error(f"Login error: {e}")
    st.stop()  # Don't render the rest of the app until logged in

# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")

    show_debug = st.toggle("Show debug / raw response", value=False)
    st.divider()

    if st.button("Log out"):
        st.session_state.auth_tokens = None
        st.session_state.messages = []
        st.session_state.pop("thread_id", None)
        st.rerun()
    st.divider()

    st.subheader("Environment")
    st.write(
        {
            "DATABASE_URL set": bool(os.getenv("DATABASE_URL")),
            "Logged in": bool(st.session_state.auth_tokens),
            "VECTOR_COLLECTION": os.getenv("VECTOR_COLLECTION", "qmr_knowledge_chunks"),
        }
    )
    st.divider()

    st.markdown(
        """
**Example questions**
- Generate a sales report for Dhaka region for January 2025
- Show me the SKU-level report for territory X last month
- Download the memo summary for February 2025
- Give me a report for all channels in Q1 2025
"""
    )

# ----------------------------------------------------------------------------
# Chat history
# ----------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Hi! I can generate reports and fetch data for you. "
                "Just tell me what you need and I'll ask for any details required."
            ),
        }
    ]

if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"st_{uuid.uuid4().hex}"

# Render existing chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ----------------------------------------------------------------------------
# Chat input
# ----------------------------------------------------------------------------
prompt = st.chat_input("Ask for a report or data…")

if prompt:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get agent response
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                result = ask_agent(
                        prompt,
                        thread_id=st.session_state.thread_id,
                        auth_tokens=st.session_state.auth_tokens,
                    )

                if isinstance(result, dict):
                    answer = result.get("answer") or result.get("content") or ""
                    artifacts = result.get("artifacts") or {}
                else:
                    answer = str(result)
                    artifacts = {}

                # Render main answer
                st.markdown(answer)

                # If the answer (or API response) contains a download URL,
                # surface it as a clearly labelled button / link.
                api_responses = artifacts.get("api_responses", [])
                for raw_resp in api_responses:
                    _extract_and_show_download_link(raw_resp)

                st.session_state.messages.append(
                    {"role": "assistant", "content": answer}
                )

                # Debug panel
                if show_debug:
                    st.divider()
                    st.subheader("🔍 Debug — Raw result")
                    try:
                        st.code(
                            json.dumps(result, indent=2, default=str), language="json",
                        )
                    except Exception:
                        st.write(result)

                    if artifacts.get("semantic_search_docs"):
                        st.subheader("📚 Retrieved knowledge chunks")
                        for doc in artifacts["semantic_search_docs"]:
                            with st.expander(doc.get("title") or "Chunk"):
                                st.write(doc)

            except Exception as e:
                err = f"Error: {e}"
                st.error(err)
                st.session_state.messages.append({"role": "assistant", "content": err})
