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

# ---------------------------------------------------------------------------
# Theme palettes — hex values derived from index.css OKLCH design tokens
# ---------------------------------------------------------------------------
LIGHT_THEME = {
    "background": "#ffffff",
    "foreground": "#333333",
    "card": "#ffffff",
    "card_foreground": "#333333",
    "primary": "#3b82f6",
    "primary_foreground": "#ffffff",
    "secondary": "#f3f4f6",
    "secondary_foreground": "#4b5563",
    "muted": "#f9fafb",
    "muted_foreground": "#6b7280",
    "accent": "#e0f2fe",
    "accent_foreground": "#1e3a8a",
    "destructive": "#ef4444",
    "destructive_foreground": "#ffffff",
    "border": "#e5e7eb",
    "input": "#e5e7eb",
    "ring": "#3b82f6",
    "sidebar": "#f9fafb",
    "sidebar_foreground": "#333333",
    "sidebar_primary": "#3b82f6",
    "sidebar_primary_foreground": "#ffffff",
    "sidebar_accent": "#e0f2fe",
    "sidebar_accent_foreground": "#1e3a8a",
    "sidebar_border": "#e5e7eb",
}


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

T = LIGHT_THEME

st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

/* ── Global ── */
html, body, [data-testid="stAppViewContainer"] {{
    background: {T["background"]};
    font-family: 'Inter', sans-serif;
}}
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] span,
[data-testid="stAppViewContainer"] li,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] .stMarkdown {{
    color: {T["foreground"]} !important;
}}
[data-testid="stSidebar"] {{
    background: {T["sidebar"]};
    border-right: 1px solid {T["sidebar_border"]};
}}
[data-testid="stSidebar"] * {{ color: {T["sidebar_foreground"]} !important; }}

/* ── Page title ── */
.app-title {{
    font-size: 1.6rem; font-weight: 700; color: {T["foreground"]};
    display: flex; align-items: center; gap: 10px;
    padding: 0.4rem 0 1.2rem;
    border-bottom: 1px solid {T["border"]}; margin-bottom: 1rem;
}}

/* ── Profile card ── */
.profile-card {{
    background: linear-gradient(135deg, {T["card"]} 0%, {T["secondary"]} 100%);
    border: 1px solid {T["border"]};
    border-radius: 12px;
    padding: 16px 18px;
    margin-bottom: 14px;
}}
.profile-name {{
    font-size: 1.05rem; font-weight: 700;
    color: {T["card_foreground"]} !important; margin-bottom: 6px;
}}
.profile-row {{
    display: flex; align-items: center; gap: 8px;
    font-size: 0.8rem; color: {T["muted_foreground"]} !important; margin: 3px 0;
}}
.role-badge {{
    display: inline-block;
    background: {T["accent"]}; color: {T["accent_foreground"]} !important;
    border: 1px solid {T["accent_foreground"]}40;
    border-radius: 20px; padding: 2px 10px;
    font-size: 0.72rem; font-weight: 600; margin-top: 8px;
}}
.status-badge {{
    display: inline-block;
    background: {T["primary"]}1a; color: {T["primary"]} !important;
    border: 1px solid {T["primary"]}33;
    border-radius: 20px; padding: 2px 10px;
    font-size: 0.72rem; font-weight: 600; margin-top: 8px; margin-left: 6px;
}}

/* ── Sidebar section headers ── */
.sidebar-section {{
    font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em;
    color: {T["muted_foreground"]} !important; text-transform: uppercase;
    margin: 14px 0 6px;
}}

/* ── Example questions ── */
.example-q {{
    background: {T["muted"]};
    border-left: 3px solid {T["primary"]};
    border-radius: 0 8px 8px 0;
    padding: 7px 12px; margin: 5px 0;
    font-size: 0.8rem; color: {T["muted_foreground"]} !important;
    cursor: default;
}}

/* ── Chat messages ── */
[data-testid="stChatMessage"] {{
    background: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 12px;
    padding: 4px 8px;
    margin-bottom: 8px;
}}
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] span,
[data-testid="stChatMessage"] li,
[data-testid="stChatMessage"] code,
[data-testid="stChatMessage"] .stMarkdown {{
    color: {T["card_foreground"]} !important;
}}

/* ── Chat input ── */
[data-testid="stChatInput"] {{
    background: {T["card"]} !important;
    border: 1px solid {T["border"]} !important;
    border-radius: 14px !important;
    padding: 4px 8px !important;
    box-shadow: none !important;
    transition: border-color 0.2s ease !important;
}}
[data-testid="stChatInput"] > div {{
    background: transparent !important;
}}
[data-testid="stChatInput"]:focus-within {{
    border-color: {T["ring"]} !important;
    box-shadow: 0 0 0 3px {T["ring"]}30 !important;
}}
[data-testid="stChatInput"] textarea {{
    background: transparent !important;
    border: none !important; outline: none !important;
    box-shadow: none !important;
    color: {T["foreground"]} !important;
    font-size: 0.95rem !important;
    caret-color: {T["ring"]} !important;
}}
[data-testid="stChatInput"] textarea::placeholder {{
    color: {T["muted_foreground"]} !important;
}}
[data-testid="stChatInput"] button {{
    background: {T["primary"]} !important;
    border-radius: 10px !important;
    border: none !important;
    color: {T["primary_foreground"]} !important;
    min-width: 36px; min-height: 36px;
}}
[data-testid="stChatInput"] button:hover {{
    background: {T["ring"]} !important;
}}
[data-testid="stChatInput"] button svg {{
    fill: {T["primary_foreground"]} !important;
    color: {T["primary_foreground"]} !important;
}}
/* bottom bar that Streamlit renders around chat input */
[data-testid="stBottom"] {{
    background: {T["background"]} !important;
}}
[data-testid="stBottom"] > div {{
    background: {T["background"]} !important;
    border-top: 1px solid {T["border"]} !important;
    padding: 10px 0 !important;
}}
/* header / toolbar area */
[data-testid="stHeader"] {{
    background: {T["background"]} !important;
}}

/* ── Form text inputs (login, etc.) ── */
[data-testid="stTextInput"] input {{
    background: {T["secondary"]} !important;
    color: {T["foreground"]} !important;
    border: 1px solid {T["border"]} !important;
    border-radius: 8px !important;
}}
[data-testid="stTextInput"] input::placeholder {{
    color: {T["muted_foreground"]} !important;
}}
[data-testid="stTextInput"] label {{
    color: {T["foreground"]} !important;
}}
/* form submit button */
[data-testid="stFormSubmitButton"] button {{
    background: {T["primary"]} !important;
    color: {T["primary_foreground"]} !important;
    border: none !important;
    border-radius: 8px !important;
}}
[data-testid="stFormSubmitButton"] button:hover {{
    background: {T["ring"]} !important;
}}

/* ── Login card ── */
.login-card {{
    background: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 16px;
    padding: 32px 28px 24px;
    margin-top: 60px;
}}
.login-title {{
    font-size: 1.3rem; font-weight: 700; color: {T["foreground"]};
    margin-top: 8px;
}}
.login-subtitle {{
    font-size: 0.85rem; color: {T["muted_foreground"]};
    margin-top: 4px;
}}

/* ── Env info ── */
.env-row {{
    display: flex; justify-content: space-between;
    font-size: 0.78rem; padding: 4px 0;
    border-bottom: 1px solid {T["border"]}; color: {T["muted_foreground"]} !important;
}}
.env-val-true  {{ color: #4ade80 !important; font-weight: 600; }}
.env-val-false {{ color: {T["destructive"]} !important; font-weight: 600; }}
.env-val-info  {{ color: {T["primary"]} !important; font-size: 0.75rem; }}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="app-title">📊 Report Assistant</div>', unsafe_allow_html=True)

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
    payload = resp.json()["data"]["data"]
    prism_tokens = payload["tokens"]["prism"]
    user = payload.get("user", {})
    return {
        "access_token": prism_tokens["tokenId"],
        "refresh_token": prism_tokens["refreshTokenId"],
        "validate_token": prism_tokens["userUid"],
        "user_info": {
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "phone": user.get("phone", ""),
            "uid": user.get("uid", ""),
            "role": user.get("roleInfo", {}).get("role", ""),
            "status": user.get("status", ""),
        },
    }


if "auth_tokens" not in st.session_state:
    st.session_state.auth_tokens = None

if st.session_state.auth_tokens is None:
    col_l, col_m, col_r = st.columns([1, 1.2, 1])
    with col_m:
        st.markdown(
            """
<div class="login-card">
  <div style="text-align:center;margin-bottom:24px;">
    <span style="font-size:2.4rem;">📊</span>
    <div class="login-title">Report Assistant</div>
    <div class="login-subtitle">Sign in to continue</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            username = st.text_input(
                "Username / Email", placeholder="e.g. abir@manush.tech"
            )
            password = st.text_input(
                "Password", type="password", placeholder="••••••••"
            )
            submitted = st.form_submit_button("Sign in →", use_container_width=True)

        if submitted:
            if not username or not password:
                st.error("Please enter both username and password.")
            else:
                try:
                    tokens = _do_login(username, password)
                    st.session_state.auth_tokens = tokens
                    st.rerun()
                except requests.exceptions.HTTPError as e:
                    st.error(
                        f"Login failed: {e.response.status_code} — {e.response.text}"
                    )
                except Exception as e:
                    st.error(f"Login error: {e}")
    st.stop()  # Don't render the rest of the app until logged in

# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
with st.sidebar:
    # ── Profile card ──
    user_info = (st.session_state.auth_tokens or {}).get("user_info", {})
    if user_info:
        st.markdown(
            f"""
<div class="profile-card">
  <div class="profile-name">👤 {user_info['name']}</div>
  <div class="profile-row">📧 {user_info['email']}</div>
  <div class="profile-row">📞 {user_info['phone']}</div>
  <div class="profile-row">🆔 {user_info['uid']}</div>
  <div style="margin-top:8px;">
    <span class="role-badge">{user_info['role']}</span>
    <span class="status-badge">{user_info['status']}</span>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    # ── Controls ──
    st.markdown('<div class="sidebar-section">Controls</div>', unsafe_allow_html=True)
    show_debug = st.toggle("Show debug / raw response", value=False)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚪 Log out", use_container_width=True):
            st.session_state.auth_tokens = None
            st.session_state.messages = []
            st.session_state.pop("thread_id", None)
            st.rerun()
    with col2:
        if st.button("🗑️ Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pop("thread_id", None)
            st.rerun()

    # ── Environment ──
    st.markdown(
        '<div class="sidebar-section">Environment</div>', unsafe_allow_html=True
    )
    db_set = bool(os.getenv("DATABASE_URL"))
    vc_name = os.getenv("VECTOR_COLLECTION", "qmr_knowledge_chunks")
    st.markdown(
        f"""
<div class="env-row"><span>DATABASE_URL</span>
  <span class="{'env-val-true' if db_set else 'env-val-false'}">{'✔ set' if db_set else '✘ not set'}</span>
</div>
<div class="env-row"><span>Logged in</span>
  <span class="env-val-true">✔ yes</span>
</div>
<div class="env-row" style="border:none"><span>Vector collection</span>
  <span class="env-val-info">{vc_name}</span>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── Example questions ──
    st.markdown(
        '<div class="sidebar-section" style="margin-top:16px">Example prompts</div>',
        unsafe_allow_html=True,
    )
    examples = [
        "SSS report for 2026-01-15, ffType 2, point Dhanmondi",
        "Query Manager Report for Jan 2026, Dhaka South, sub-channels BCC & RCC",
        "Route Wise STT report 2026-01-01 to 2026-02-01, SKU, Dhanmondi",
        "Route Wise Memo report 2026-01-01 to 2026-01-31, SKU, Dhanmondi",
        "Survey report ID 1, 2026-01-01 to 2026-01-31, Dhaka South",
    ]
    for ex in examples:
        st.markdown(f'<div class="example-q">💬 {ex}</div>', unsafe_allow_html=True)

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
