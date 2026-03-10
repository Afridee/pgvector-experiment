# 🚀 API + Knowledge Agent (Report Assistant)

**System:** macOS (Intel) with Homebrew  
**Date:** March 2026  
**Purpose:** Hybrid API-calling + RAG agent that retrieves context from a pgvector knowledge base and calls external REST APIs to generate reports and answer questions.

---

## **TABLE OF CONTENTS**

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Install PostgreSQL](#install-postgresql)
4. [Install pgvector Extension](#install-pgvector)
5. [Configure PATH](#configure-path)
6. [Create Database](#create-database)
7. [Setup Python Environment](#setup-python-environment)
8. [Environment Variables](#environment-variables)
9. [Add API Knowledge](#add-api-knowledge)
10. [Run Ingestion](#run-ingestion)
11. [Run the App](#run-the-app)
12. [Usage Examples](#usage-examples)
13. [Troubleshooting](#troubleshooting)
14. [Cleanup](#cleanup)

---

## **1. ARCHITECTURE OVERVIEW**

```
User Question (Streamlit chat)
          │
          ▼
┌─────────────────────────────────────────────┐
│  Report Assistant  (backend/agent.py)       │
│  GPT-4o + LangGraph checkpointing           │
│  - Understands the request                  │
│  - Retrieves API docs from knowledge base   │
│  - Collects required parameters from user   │
│  - Calls external API                       │
└─────────────────────────────────────────────┘
          │
          ├──────────────────────────────────────┐
          ▼                                      ▼
  ┌─────────────────────────┐        ┌──────────────────────┐
  │  semantic_search_tool   │        │  api_call            │
  │  RAG over pgvector      │        │  HTTP GET/POST/etc.  │
  │  Retrieves API docs,    │        │  Injects API_TOKEN   │
  │  required params, etc.  │        │  from environment    │
  └─────────────────────────┘        └──────────────────────┘
          │                                      │
          ▼                                      ▼
┌──────────────────────────┐        ┌────────────────────────┐
│  PostgreSQL (pgvector)   │        │  External REST APIs    │
│  knowledge_chunks        │        │  (configured in        │
│  collection — API docs,  │        │  knowledge_chunks.txt) │
│  parameters, responses   │        │                        │
└──────────────────────────┘        └────────────────────────┘

  Conversation history stored in PostgreSQL via LangGraph PostgresSaver
```

## **2. PREREQUISITES**

- macOS (Intel Mac)
- Homebrew installed
- Python 3.12+ installed
- [uv](https://docs.astral.sh/uv/) installed
- OpenAI API key (get one at https://platform.openai.com/api-keys)
- API token for the external REST APIs the agent will call

### Verify Prerequisites

```bash
brew --version       # Homebrew 4.x+
python --version     # Python 3.12+
uv --version         # uv 0.x+
```

### Install uv (if not already installed)

```bash
brew install uv
```

---

## **3. INSTALL POSTGRESQL**

```bash
brew update
brew install postgresql@15

# Start and enable on login
brew services start postgresql@15
brew services list | grep postgresql@15
# Expected: postgresql@15  started  ...
```

---

## **4. INSTALL PGVECTOR**

```bash
brew install pgvector
```

---

## **5. CONFIGURE PATH**

```bash
# Intel Mac
sed -i '' '/postgresql@15/d' ~/.zshrc
echo 'export PATH="/usr/local/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

which psql      # /usr/local/opt/postgresql@15/bin/psql
which createdb  # /usr/local/opt/postgresql@15/bin/createdb
```

---

## **6. CREATE DATABASE**

```bash
# Create a PostgreSQL superuser matching your macOS username (if needed)
createuser -s $(whoami)

# Create the application database
createdb qmrdb

# Enable pgvector
psql qmrdb -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

> **✅ Checkpoint:** `qmrdb` exists and pgvector is enabled.
> PostgreSQL is used for two things: **pgvector embeddings** (knowledge base) and **LangGraph conversation checkpoints**. No application data tables are required.

---

## **7. SETUP PYTHON ENVIRONMENT**

```bash
cd /path/to/pgvector-experiment

# Install all dependencies from pyproject.toml into a managed .venv
uv sync
```

All subsequent commands (`uv run python ...`) automatically use the project's virtual environment — no manual activation needed.

**Key dependencies** (see `pyproject.toml`):

| Package                                      | Purpose                                       |
| -------------------------------------------- | --------------------------------------------- |
| `langchain`, `langchain-openai`              | LLM + tools framework                         |
| `langchain-postgres`                         | pgvector vector store                         |
| `langgraph`, `langgraph-checkpoint-postgres` | Agent graph + persistent conversation history |
| `psycopg[binary]`, `psycopg2-binary`         | PostgreSQL drivers                            |
| `streamlit`                                  | Web chat UI                                   |
| `python-dotenv`                              | `.env` loading                                |

---

## **8. ENVIRONMENT VARIABLES**

Create a `.env` file in your project root:

```bash
cat > .env << 'EOF'
# OpenAI
OPENAI_API_KEY=sk-your-actual-openai-key-here

# Base URL for all external API calls (required)
BASE_URL=https://api.example.com

# PostgreSQL — used for pgvector embeddings and LangGraph checkpoints
DATABASE_URL=postgresql://localhost:5432/qmrdb

# (Optional) separate DB for LangGraph checkpoints — defaults to DATABASE_URL
CHECKPOINT_DB_URL=postgresql://localhost:5432/qmrdb

# pgvector collection name (must match what ingest.py wrote)
VECTOR_COLLECTION=qmr_knowledge_chunks

# Path to API knowledge chunks file
CHUNKS_FILE=knowledge_chunks.txt

# Fallback bearer token for unauthenticated usage (Streamlit login overrides this)
API_TOKEN=your-api-token-here
EOF
```

> **⚠️ IMPORTANT:** Replace placeholder values with your real credentials. `BASE_URL` and `OPENAI_API_KEY` are required — the agent will raise an error at startup if either is missing. `API_TOKEN` is only used as a fallback when no login session is active.

---

## **9. ADD API KNOWLEDGE**

The agent has no built-in knowledge of your APIs. You teach it by writing knowledge chunks in `knowledge_chunks.txt`. Read `instructions.md` for the full authoring guide.

Each chunk covers one aspect of one endpoint:

| Chunk                          | What it covers                                     |
| ------------------------------ | -------------------------------------------------- |
| `[Name] — Endpoint and Method` | URL, HTTP method, authentication note              |
| `[Name] — Required Parameters` | Fields the agent MUST collect before calling       |
| `[Name] — Optional Parameters` | Fields with defaults or that can be omitted        |
| `[Name] — Response`            | Response shape, field paths, download URL handling |

**Minimal example:**

```text
---
title: My Report API — Endpoint and Method
tags: topic:endpoint, applies_to:my_report, api_template
content:
Purpose:
- Generates a sales report for the given date range.

Endpoint:
- Method: POST
- URL: https://api.example.com/v1/reports/sales

Payload/Headers:
- Content-Type: application/json
- Auth token is injected automatically — do NOT ask the user for it.
---

---
title: My Report API — Required Parameters
tags: topic:parameters, applies_to:my_report, business_rule
content:
Before calling this endpoint you MUST collect:
- region     : string — e.g. "Dhaka", "Rajshahi"
- start_date : string YYYY-MM-DD
- end_date   : string YYYY-MM-DD

Do NOT call the API until all three are provided.
---
```

After adding or editing chunks, re-run ingestion (see next section).

---

## **10. RUN INGESTION**

Ingestion reads `knowledge_chunks.txt`, generates embeddings, and stores them in pgvector.
Run this **once initially**, then again whenever `knowledge_chunks.txt` changes.

```bash
uv run python ingest.py
```

**Expected output:**

```
======================================================================
QMR KNOWLEDGE (.TXT) TO VECTOR INGESTION
======================================================================

📄 Loading QMR knowledge chunks from: knowledge_chunks.txt
   ✓ Loaded 30 knowledge chunks

📊 Ingestion Summary:
   Total documents: 30
   Estimated tokens: ~7,500
   Estimated cost: ~$0.0002

🚀 Generating embeddings (this may take some seconds)...

✅ Success! Created 30 embeddings
   Collection name: qmr_knowledge_chunks
   Storage: PostgreSQL (pgvector)

======================================================================
✅ INGESTION COMPLETE!
======================================================================
```

> **✅ Checkpoint:** All knowledge chunks embedded and stored. The document count will vary depending on how many chunks are in `knowledge_chunks.txt`.

---

## **11. RUN THE APP**

### Streamlit (recommended)

```bash
uv run streamlit run streamlit_app.py
```

Open http://localhost:8501 in your browser.

The **Report Assistant** sidebar shows a toggle for debug output (raw agent response + retrieved knowledge chunks) and displays the current state of required environment variables.

### Programmatic usage

```python
from backend.agent import ask_agent

result = ask_agent(
    question="Generate an SSS report for 2026-01-15, ffType 2, point Dhanmondi",
    thread_id="my-session-001",
    auth_tokens={
        "access_token": "...",
        "refresh_token": "...",
        "validate_token": "...",
    },
)
print(result["answer"])
```

`ask_agent` returns:

```python
{
    "answer": "...",           # Final assistant message
    "artifacts": {
        "semantic_search_docs": [...],   # Knowledge chunks retrieved (if any)
        "api_responses": [...],          # Raw API responses (if any)
    },
    "raw": {...}               # Full LangGraph result (messages, metadata, etc.)
}
```

Each call is tied to a `thread_id` — LangGraph persists conversation history in PostgreSQL so the agent remembers context across turns.

---

## **12. USAGE EXAMPLES**

### Generate an SSS report

**Prompt:**

> Generate an SSS report for 2026-01-15, ffType 2, point Dhanmondi

**Agent behaviour:** Searches knowledge base for the SSS Report endpoint, resolves "Dhanmondi" to its point ID using the Location Reference chunks, then calls the API and presents the structured data.

### Generate a Query Manager Report

**Prompt:**

> Generate a Query Manager Report for January 2026, Dhaka South region, sub-channels BCC and RCC, product IDs 1 and 2, productType SKU, reportType stt and memo

**Agent behaviour:** Retrieves QMR endpoint documentation, resolves the region ID, constructs the payload with all required parameters, calls the API, and presents the download link.

### Generate a Route Wise report

**Prompt:**

> Generate a Route Wise STT report from 2026-01-01 to 2026-02-01, type SKU, for Dhanmondi point

**Agent behaviour:** Searches knowledge base for Route Wise STT endpoint, resolves "Dhanmondi" to its point ID, then calls the API and surfaces the download link.

### Generate a Survey report

**Prompt:**

> Generate a Survey report for survey ID 1, from 2026-01-01 to 2026-01-31, Dhaka South region

**Agent behaviour:** Retrieves Survey Report endpoint docs, resolves the region ID, and calls the API with `surveyId`, `startDate`, `endDate`, and `regionId`.

### Debug mode

Enable **Show debug / raw response** in the sidebar to inspect:

- Which knowledge chunks the agent retrieved
- The raw API response before formatting

---

## **13. TROUBLESHOOTING**

### `psql: command not found`

```bash
echo 'export PATH="/usr/local/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### PostgreSQL not running

```bash
brew services list | grep postgresql@15
brew services start postgresql@15
```

### `CREATE EXTENSION vector` fails

```bash
brew reinstall pgvector
psql qmrdb -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### `DATABASE_URL is not set` or missing env vars

Ensure `.env` exists in your working directory and contains all required keys. Double-check with:

```bash
cat .env | grep -E "DATABASE_URL|API_TOKEN|OPENAI_API_KEY|BASE_URL"
```

### `No module named 'langchain'` (or any other package)

Sync dependencies from `pyproject.toml`:

```bash
uv sync
```

### Agent says it doesn't know about an endpoint

The agent only knows what is in `knowledge_chunks.txt`. Add the missing endpoint documentation as new chunks, then re-run ingestion:

```bash
uv run python ingest.py
```

Enable **Show debug / raw response** in the Streamlit sidebar to see which chunks were (or weren't) retrieved for a query.

### Agent calls the wrong endpoint or uses wrong parameters

1. Check the relevant chunk in `knowledge_chunks.txt` — ensure the title is descriptive and the content is precise.
2. Re-run ingestion after any edits.
3. Check that `VECTOR_COLLECTION` in `.env` matches the collection used during ingestion.

### `Expected BaseCheckpointSaver, got ...`

Ensure `langgraph` and `langgraph-checkpoint-postgres` are installed and up to date:

```bash
uv add --upgrade langgraph langgraph-checkpoint-postgres
```

### API calls return `401 Unauthorized`

Verify `API_TOKEN` is set correctly in `.env`. The token is injected as a `Bearer` header automatically — never put it in knowledge chunks.

---

## **14. CLEANUP**

### Stop services

```bash
brew services stop postgresql@15
```

### Drop database

```bash
dropdb qmrdb
```

### Remove project virtual environment

```bash
rm -rf .venv
```

### Uninstall (optional)

```bash
brew uninstall postgresql@15
brew uninstall pgvector
sed -i '' '/postgresql@15/d' ~/.zshrc && source ~/.zshrc
```

---

**Questions?** Review the troubleshooting section or ask the agent directly via `streamlit_app.py`. To add new APIs, see `instructions.md`.
