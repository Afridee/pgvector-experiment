# 🚀 QMR Database + Knowledge Agent

**System:** macOS (Intel) with Homebrew  
**Date:** March 2026  
**Purpose:** Hybrid Text-to-SQL + RAG agent for QMR (Outlet Query Manager Report) questions

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
9. [Run Ingestion](#run-ingestion)
10. [Run Tests](#run-tests)
11. [Run the App](#run-the-app)
12. [Usage Examples](#usage-examples)
13. [Troubleshooting](#troubleshooting)
14. [Cleanup](#cleanup)

---

## **1. ARCHITECTURE OVERVIEW**

```
User Question (Streamlit / CLI)
          │
          ▼
┌─────────────────────────────────────────────┐
│  QMR Agent  (agent.py)                      │
│  GPT-4o + LangGraph checkpointing           │
│  - Analyzes question                        │
│  - Chooses tool(s)                          │
└─────────────────────────────────────────────┘
          │
          ├──────────────────┬─────────────────────┐
          ▼                  ▼                     ▼
  ┌──────────────┐  ┌─────────────────┐  ┌───────────────┐
  │  SQL Toolkit │  │ semantic_search │  │   Both tools  │
  │  (read-only) │  │ _tool (pgvector)│  │  in sequence  │
  └──────────────┘  └─────────────────┘  └───────────────┘
          │                  │
          ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│  PostgreSQL Database                                    │
│  ┌────────────────────┐  ┌───────────────────────────┐ │
│  │  QMR Cache Tables  │  │  pgvector store            │ │
│  │  monthly_order_    │  │  (qmr_knowledge_chunks)    │ │
│  │  cache_YYYY_MM     │  │  QMR rules, templates,     │ │
│  │  daily_order_cache │  │  ProductType mapping, etc. │ │
│  └────────────────────┘  └───────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
          │
          ▼
  Answer + (optional) source chunks
```

## **2. PREREQUISITES**

- macOS (Intel Mac)
- Homebrew installed
- Python 3.10+ installed
- [uv](https://docs.astral.sh/uv/) installed
- OpenAI API key (get one at https://platform.openai.com/api-keys)

### Verify Prerequisites

```bash
brew --version       # Homebrew 4.x+
python --version     # Python 3.10+
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

# Create a read-only agent user (security best practice)
psql qmrdb -c "
  CREATE USER readonly_agent WITH PASSWORD 'agent123';
  GRANT CONNECT ON DATABASE qmrdb TO readonly_agent;
  GRANT USAGE ON SCHEMA public TO readonly_agent;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_agent;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_agent;
"
```

> **✅ Checkpoint:** `qmrdb` exists, pgvector enabled, `readonly_agent` user created.

---

## **7. SETUP PYTHON ENVIRONMENT**

```bash
mkdir -p ~/qmr-agent && cd ~/qmr-agent

# Initialise a uv-managed project (creates pyproject.toml + .venv)
uv init --python 3.12

# Add all runtime dependencies
uv add \
  langchain \
  langchain-openai \
  langchain-postgres \
  langchain-community \
  langgraph \
  "psycopg[binary]" \
  sqlalchemy \
  python-dotenv \
  streamlit
```

All subsequent commands (`uv run python ...`) automatically use the project's virtual environment — no manual activation needed.

---

## **8. ENVIRONMENT VARIABLES**

Create a `.env` file in your project root:

```bash
cat > .env << 'EOF'
# OpenAI
OPENAI_API_KEY=sk-your-actual-openai-key-here

# Main DB (read-write: vector store + checkpoints)
DATABASE_URL=postgresql://localhost:5432/qmrdb

# Read-only DB for SQL agent queries
READONLY_DATABASE_URL=postgresql://readonly_agent:agent123@localhost:5432/qmrdb

# (Optional) separate DB for LangGraph checkpoints — defaults to DATABASE_URL
CHECKPOINT_DB_URL=postgresql://localhost:5432/qmrdb

# pgvector collection name
VECTOR_COLLECTION=qmr_knowledge_chunks

# Path to QMR knowledge chunks file (used by ingest.py)
QMR_CHUNKS_FILE=qmr_semantic_knowledge_chunks.txt
EOF
```

> **⚠️ IMPORTANT:** Replace `sk-your-actual-openai-key-here` with your real key.

---

## **9. RUN INGESTION**

Ingestion reads `qmr_semantic_knowledge_chunks.txt`, generates embeddings, and stores them in pgvector.
Run this **once initially**, then again whenever the knowledge file changes.

```bash
uv run python ingest.py
```

**Expected output:**

```
======================================================================
QMR KNOWLEDGE (.TXT) TO VECTOR INGESTION
======================================================================

📄 Loading QMR knowledge chunks from: qmr_semantic_knowledge_chunks.txt
   ✓ Loaded 9 knowledge chunks

📊 Ingestion Summary:
   Total documents: 9
   Estimated tokens: ~2,250
   Estimated cost: ~$0.0001

🚀 Generating embeddings (this may take some seconds)...

✅ Success! Created 9 embeddings
   Collection name: qmr_knowledge_chunks
   Storage: PostgreSQL (pgvector)

======================================================================
✅ INGESTION COMPLETE!
======================================================================
```

> **✅ Checkpoint:** All knowledge chunks embedded and stored.

---

## **10. RUN TESTS**

```bash
uv run python test.py
```

The test suite covers:

| # | Test | Type |
|---|------|------|
| 1 | Schema inspection | SQL |
| 2 | Count query (`daily_order_cache`) | SQL |
| 3 | Memo calculation rules (SKU vs Total) | Semantic |
| 4 | Date split rules (today within range) | Semantic |
| 5 | ProductType → cache column mapping | Semantic |
| 6 | Distributor filter SQL clause | Semantic |
| 7 | Full QMR SQL generation — SKU, past range | SQL gen |
| 8 | Full QMR SQL generation — Total productType | SQL gen |

**Expected output:**

```
======================================================================
AUTOMATED AGENT TESTS
======================================================================

🧪 TEST 1/8: SQL — Schema inspection
   ...
   ✅ Answer: The available tables are: ...

...

======================================================================
TEST SUMMARY
======================================================================
✅ Passed: 8/8
❌ Failed: 0/8

🎉 All tests passed! The agent is working correctly.
======================================================================
```

---

## **11. RUN THE APP**

### Streamlit (recommended)

```bash
uv run streamlit run streamlit_app.py
```

Open http://localhost:8501 in your browser.

### Programmatic usage

```python
from agent import ask_database

result = ask_database(
    question="Generate QMR SQL for productType=Brand, startDate=2026-01-01, endDate=2026-01-31",
    thread_id="my-session-001",
)
print(result["answer"])
```

`ask_database` returns:

```python
{
    "answer": "...",           # LLM final answer (JSON with primaryDataQuery + retailerOrderDataQuery)
    "artifacts": {             # Optional: only present when semantic search was used
        "semantic_search_docs": [...]
    },
    "raw": {...}               # Full LangGraph result (messages, metadata, etc.)
}
```

---

## **12. USAGE EXAMPLES**

### QMR SQL Generation

**Prompt:**
> Generate QMR SQL for productType=SKU, startDate=2025-12-01, endDate=2025-12-31, no filters. Today is 2026-03-02.

**Expected response format:**
```json
{
  "primaryDataQuery": "SELECT ... FROM monthly_order_cache_2025_12 o WHERE ...",
  "retailerOrderDataQuery": "SELECT ... FROM monthly_order_cache_2025_12 o WHERE ...",
  "notes": [
    "Date range is fully in the past — only monthly tables used.",
    "MV tables used: monthly_order_cache_2025_12",
    "productType=SKU → o.sku_id selected and grouped"
  ]
}
```

### QMR Rules (RAG)

**Prompt:**
> How is the Memo distinct key different for primary vs retailer order queries?

**Expected:** The agent retrieves the relevant knowledge chunks and explains:
- Primary query Memo = `DISTINCT retailer_id || '-' || DATE(order_placed_at) || '-' || product_id` (product_id omitted for Total)
- Retailer order query "Total Memo" = `DISTINCT retailer_id || '-' || DATE(order_placed_at)` (never includes product_id)

### Date Split

**Prompt:**
> startDate=2026-02-01, endDate=2026-03-15. Today is 2026-03-02. Which tables should be used?

**Expected:** MV portion uses `monthly_order_cache_2026_02` with upper bound `< '2026-03-02'`; daily portion uses `daily_order_cache` from `>= '2026-03-02'` to `< '2026-03-16'`.

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

### `READONLY_DATABASE_URL is not set`

Ensure `.env` exists in your working directory and contains all required keys. Double-check with:

```bash
cat .env | grep DATABASE_URL
```

### `No module named 'langchain'` (or any other package)

```bash
uv add langchain langchain-openai langchain-postgres \
  langchain-community langgraph "psycopg[binary]" sqlalchemy python-dotenv streamlit
```

Or sync from `pyproject.toml` (e.g. after cloning the repo):

```bash
uv sync
```

### Agent returns wrong / empty SQL

1. Re-run ingestion to refresh the knowledge base:
   ```bash
   uv run python ingest.py
   ```
2. Run tests to verify semantic retrieval is working:
   ```bash
   uv run python test.py
   ```
3. Check that `VECTOR_COLLECTION` in `.env` matches the collection used during ingestion.

### `Expected BaseCheckpointSaver, got ...`

Ensure `langgraph` is installed and up to date:

```bash
uv add --upgrade langgraph
```

---

## **14. CLEANUP**

### Stop services

```bash
brew services stop postgresql@15
```

### Drop database and users

```bash
dropdb qmrdb
psql postgres -c "DROP USER IF EXISTS readonly_agent;"
```

### Remove project

```bash
rm -rf ~/qmr-agent
```

### Uninstall (optional)

```bash
brew uninstall postgresql@15
brew uninstall pgvector
sed -i '' '/postgresql@15/d' ~/.zshrc && source ~/.zshrc
```

---

## **APPENDIX — QMR SQL Rules Summary**

| Rule | Detail |
|------|--------|
| Allowed tables | `monthly_order_cache_YYYY_MM`, `daily_order_cache` only |
| Required output | `primaryDataQuery` + `retailerOrderDataQuery` (always both) |
| Total productType | `retailerOrderDataQuery` must be `SELECT 1 as "Dummy"` |
| Date bounds | `>= lower` (inclusive), `< upper` (exclusive) |
| Date split | If today ∈ [startDate, endDate]: MV portion < today; daily ≥ today |
| Memo key (primary) | `retailer_id \|\| '-' \|\| DATE(order_placed_at)` + product_id (non-Total) |
| Total Memo key | `retailer_id \|\| '-' \|\| DATE(order_placed_at)` (never product_id) |
| Filters | Optional AND clauses; ignore empty or `"all"` lists |

---

**Questions?** Review the troubleshooting section or ask the agent directly via `streamlit_app.py`!