"""
Streamlit Chat App — API + Knowledge Agent

Calls ask_agent(question, thread_id) from backend.agent.
"""

import json
import os
import uuid

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

# ---------------------------------------------------------------------------
# Brand palette — custom CSS overrides
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    /* ========== Chat bubbles ========== */
    /* Assistant messages */
    .stChatMessage:has(.stAvatar [data-testid="chatAvatarIcon-assistant"]),
    .stChatMessage:has(div[data-testid="stChatMessageAvatarAssistant"]),
    div[data-testid="stChatMessage"]:nth-child(odd) {
        background-color: #FFFFFF !important;
        border: 1px solid #E2DFD9 !important;
        border-radius: 0.75rem !important;
        box-shadow: 0 2px 6px rgba(44, 44, 44, 0.07) !important;
        padding: 1rem 1.25rem !important;
    }
    /* User messages */
    .stChatMessage:has(.stAvatar [data-testid="chatAvatarIcon-user"]),
    .stChatMessage:has(div[data-testid="stChatMessageAvatarUser"]),
    div[data-testid="stChatMessage"]:nth-child(even) {
        background-color: #EAE6DF !important;
        border: 1px solid #D9D4CC !important;
        border-radius: 0.75rem !important;
        box-shadow: 0 2px 6px rgba(44, 44, 44, 0.07) !important;
        padding: 1rem 1.25rem !important;
    }
    /* Shared bubble spacing */
    .stChatMessage {
        margin-bottom: 0.5rem !important;
    }

    /* ========== Chat input ========== */
    .stChatInput > div {
        border-color: #D4A017 !important;
    }
    .stChatInput textarea:focus {
        border-color: #D4A017 !important;
        box-shadow: 0 0 0 1px #D4A017 !important;
    }

    /* ========== Alert banners ========== */
    /* Error */
    div[data-testid="stAlert"] div[role="alert"][data-baseweb*="negative"],
    div[data-testid="stNotification"][data-kind="Error"],
    .element-container div[data-baseweb="notification"][kind="negative"] {
        background-color: #fdeaea !important;
        border-left: 4px solid #E05252 !important;
        color: #2C2C2C !important;
    }
    /* Success */
    div[data-testid="stAlert"] div[role="alert"][data-baseweb*="positive"],
    div[data-testid="stNotification"][data-kind="Success"],
    .element-container div[data-baseweb="notification"][kind="positive"] {
        background-color: #e8f5ec !important;
        border-left: 4px solid #4CAF72 !important;
        color: #2C2C2C !important;
    }
    /* Warning */
    div[data-testid="stAlert"] div[role="alert"][data-baseweb*="warning"],
    div[data-testid="stNotification"][data-kind="Warning"],
    .element-container div[data-baseweb="notification"][kind="warning"] {
        background-color: #fdf0ee !important;
        border-left: 4px solid #E8A09A !important;
        color: #2C2C2C !important;
    }

    /* ========== Spinner accent ========== */
    .stSpinner > div > div,
    .stSpinner svg circle {
        border-top-color: #E8861A !important;
        stroke: #E8861A !important;
    }
    .stSpinner > div > span,
    .stSpinner p {
        color: #E8861A !important;
    }

    /* ========== Dividers ========== */
    hr {
        border-color: #E2DFD9 !important;
    }

    /* ========== Scrollbar ========== */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: #F8F7F5; }
    ::-webkit-scrollbar-thumb { background: #DDD9D3; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #CCC8C1; }

    /* ========== Sidebar ========== */
    section[data-testid="stSidebar"] {
        background-color: #F0EEEB !important;
        color: #2C2C2C !important;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #2C2C2C !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Report Assistant")

# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")

    show_debug = st.toggle("Show debug / raw response", value=False)
    st.divider()

    st.subheader("Environment")
    st.write(
        {
            "DATABASE_URL set": bool(os.getenv("DATABASE_URL")),
            "API_TOKEN set": bool(os.getenv("API_TOKEN")),
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
                result = ask_agent(prompt, thread_id=st.session_state.thread_id)

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
