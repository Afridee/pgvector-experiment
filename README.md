# 🚀 Complete Guide: Database Agent with PostgreSQL + pgvector + RAG

**System:** macOS (Intel) with Homebrew  
**Date:** February 2026  
**Purpose:** Build a hybrid SQL + Vector search database agent

---

## **TABLE OF CONTENTS**

1. [Prerequisites](#prerequisites)
2. [Install PostgreSQL](#install-postgresql)
3. [Install pgvector Extension](#install-pgvector)
4. [Configure PATH](#configure-path)
5. [Create Database](#create-database)
6. [Load Sample Data](#load-sample-data)
7. [Setup Python Environment](#setup-python-environment)
8. [Create Application Files](#create-application-files)
9. [Run the Application](#run-the-application)
10. [Usage Examples](#usage-examples)
11. [Troubleshooting](#troubleshooting)
12. [Cleanup](#cleanup)

---

## **1. PREREQUISITES**

### **Required:**
- macOS (Intel Mac)
- Homebrew installed
- Python 3.8+ installed
- OpenAI API key

### **Verify Prerequisites:**

```bash
# Check Homebrew
brew --version
# Expected: Homebrew 4.x.x or higher

# Check Python
python --version
# Expected: Python 3.8+ or higher

# Check if you have an OpenAI API key
# Get one from: https://platform.openai.com/api-keys
```

---

## **2. INSTALL POSTGRESQL**

### **Install PostgreSQL 15:**

```bash
# Update Homebrew
brew update

# Install PostgreSQL 15
brew install postgresql@15
```

### **Start PostgreSQL Service:**

```bash
# Start PostgreSQL and set it to run on startup
brew services start postgresql@15

# Verify it's running
brew services list | grep postgresql@15
# Expected output: postgresql@15  started  afridee  ~/Library/LaunchAgents/...
```

---

## **3. INSTALL PGVECTOR**

### **Install pgvector Extension:**

```bash
# Install pgvector for vector similarity search
brew install pgvector
```

---

## **4. CONFIGURE PATH**

### **Add PostgreSQL to PATH (Intel Mac):**

```bash
# Remove any existing postgresql@15 entries from .zshrc
sed -i '' '/postgresql@15/d' ~/.zshrc

# Add PostgreSQL bin directory to PATH (Intel Mac specific)
echo 'export PATH="/usr/local/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc

# Reload shell configuration
source ~/.zshrc

# Verify PATH is configured correctly
which psql
# Expected: /usr/local/opt/postgresql@15/bin/psql

which createdb
# Expected: /usr/local/opt/postgresql@15/bin/createdb
```

**✅ Checkpoint:** Both `psql` and `createdb` commands should be found.

---

## **5. CREATE DATABASE**

### **Create PostgreSQL User (if needed):**

```bash
# Create a PostgreSQL user matching your macOS username
createuser -s $(whoami)
# Note: This command may show no output if successful
```

### **Create Test Database:**

```bash
# Create database named 'testdb'
createdb testdb

# Verify database was created
psql -l | grep testdb
# Expected: testdb | <your-username> | ...
```

### **Enable pgvector Extension:**

```bash
# Connect to testdb and enable vector extension
psql testdb -c "CREATE EXTENSION IF NOT EXISTS vector;"
# Expected output: CREATE EXTENSION

# Verify extension is installed
psql testdb -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
# Expected: Should show vector extension details
```

**✅ Checkpoint:** Database `testdb` is created and pgvector extension is enabled.

---

## **6. LOAD SAMPLE DATA**

### **Create SQL Schema File:**

```bash
# Create SQL file with sample e-commerce database
cat > ~/create_schema.sql << 'EOF'
-- ============================================================================
-- Sample E-commerce Database Schema
-- ============================================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- CREATE TABLES
-- ============================================================================

-- Products table: Store product information
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    price NUMERIC(10, 2),
    stock_quantity INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Customers table: Store customer information
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    city VARCHAR(100),
    country VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders table: Store order transactions
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    total_amount NUMERIC(10, 2),
    order_date DATE DEFAULT CURRENT_DATE,
    status VARCHAR(50)
);

-- Reviews table: Store product reviews
CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    customer_id INTEGER REFERENCES customers(id),
    review_text TEXT,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INSERT SAMPLE DATA
-- ============================================================================

-- Insert Products (10 sample products)
INSERT INTO products (name, description, category, price, stock_quantity) VALUES
('Gaming Laptop Pro X1', 'High-performance gaming laptop with RTX 4080, 32GB RAM, perfect for AAA gaming and video editing. Features 17-inch 240Hz display and RGB keyboard.', 'Laptops', 1899.99, 15),
('UltraBook Air M2', 'Lightweight ultrabook for professionals, 13-inch display, 16GB RAM, ideal for business travel and productivity. All-day battery life.', 'Laptops', 1299.99, 25),
('Wireless Gaming Mouse', 'Ergonomic wireless mouse with 16000 DPI sensor, perfect for competitive gaming. Features customizable RGB lighting and programmable buttons.', 'Accessories', 79.99, 50),
('4K Monitor 32"', 'Professional 4K IPS monitor with HDR support, perfect for content creation and gaming. 144Hz refresh rate and USB-C connectivity.', 'Monitors', 699.99, 20),
('Mechanical Keyboard RGB', 'Premium mechanical keyboard with Cherry MX switches, full RGB backlighting. Perfect for gaming and typing enthusiasts.', 'Accessories', 149.99, 30),
('Noise-Cancelling Headphones', 'Premium wireless headphones with active noise cancellation, 30-hour battery life. Perfect for travel and focus work.', 'Audio', 299.99, 40),
('Webcam 4K Pro', 'Professional 4K webcam with auto-focus and built-in microphone. Ideal for streaming and video conferencing.', 'Accessories', 129.99, 35),
('Portable SSD 2TB', 'Ultra-fast portable SSD with 2TB storage, USB 3.2 Gen 2. Perfect for photographers and video editors.', 'Storage', 249.99, 45),
('Gaming Chair Elite', 'Ergonomic gaming chair with lumbar support and adjustable armrests. Premium leather material for all-day comfort.', 'Furniture', 399.99, 12),
('Smartphone Pro 15', 'Latest flagship smartphone with 108MP camera, 5G connectivity, and all-day battery. Perfect for photography enthusiasts.', 'Phones', 999.99, 60);

-- Insert Customers (5 sample customers)
INSERT INTO customers (name, email, city, country) VALUES
('Alice Johnson', 'alice@email.com', 'New York', 'USA'),
('Bob Smith', 'bob@email.com', 'London', 'UK'),
('Carol Martinez', 'carol@email.com', 'Madrid', 'Spain'),
('David Chen', 'david@email.com', 'Singapore', 'Singapore'),
('Emma Wilson', 'emma@email.com', 'Toronto', 'Canada');

-- Insert Orders (10 sample orders from January-February 2026)
INSERT INTO orders (customer_id, product_id, quantity, total_amount, order_date, status) VALUES
(1, 1, 1, 1899.99, '2026-01-15', 'delivered'),
(2, 3, 2, 159.98, '2026-01-20', 'delivered'),
(3, 6, 1, 299.99, '2026-02-05', 'delivered'),
(4, 10, 1, 999.99, '2026-02-08', 'shipped'),
(5, 2, 1, 1299.99, '2026-02-09', 'processing'),
(1, 4, 1, 699.99, '2026-01-25', 'delivered'),
(2, 5, 1, 149.99, '2026-02-01', 'shipped'),
(3, 7, 2, 259.98, '2026-02-03', 'delivered'),
(4, 8, 1, 249.99, '2026-02-06', 'processing'),
(5, 9, 1, 399.99, '2026-02-07', 'shipped');

-- Insert Reviews (8 sample reviews)
INSERT INTO reviews (product_id, customer_id, review_text, rating) VALUES
(1, 1, 'Amazing gaming laptop! Runs all my games at ultra settings smoothly. The 240Hz display is incredibly smooth. Highly recommend for serious gamers.', 5),
(3, 2, 'Perfect mouse for FPS games. The sensor is super accurate and the wireless connection is flawless. Battery lasts for weeks.', 5),
(6, 3, 'Best noise cancellation I have experienced. Perfect for blocking out noise during flights and in the office. Sound quality is excellent.', 5),
(10, 4, 'Camera quality is outstanding! Low-light performance is impressive. Battery easily lasts a full day. Best phone I have owned.', 5),
(2, 5, 'Lightweight and perfect for travel. Battery life is amazing - easily 12+ hours. Great for productivity work.', 4),
(4, 1, 'Beautiful 4K display with accurate colors. Perfect for photo editing and watching movies. The 144Hz makes gaming smooth too.', 5),
(5, 2, 'Great mechanical keyboard. Cherry MX switches feel amazing. RGB lighting is customizable and looks fantastic.', 4),
(8, 3, 'Super fast SSD. Transfer speeds are incredible. Perfect for backing up large video files. Compact and portable.', 5);

-- ============================================================================
-- CREATE READ-ONLY USER FOR AGENT (Security Best Practice)
-- ============================================================================

CREATE USER readonly_agent WITH PASSWORD 'agent123';
GRANT CONNECT ON DATABASE testdb TO readonly_agent;
GRANT USAGE ON SCHEMA public TO readonly_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_agent;

-- Ensure future tables are also accessible
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_agent;

-- ============================================================================
-- VERIFY SETUP
-- ============================================================================

SELECT '✅ Database setup complete!' as status;

-- Show record counts
SELECT 'Products' as table_name, COUNT(*) as record_count FROM products
UNION ALL
SELECT 'Customers', COUNT(*) FROM customers
UNION ALL
SELECT 'Orders', COUNT(*) FROM orders
UNION ALL
SELECT 'Reviews', COUNT(*) FROM reviews
ORDER BY table_name;
EOF
```

### **Load Data into Database:**

```bash
# Execute the SQL file
psql testdb -f ~/create_schema.sql
```

**Expected Output:**
```
CREATE EXTENSION
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE TABLE
INSERT 0 10
INSERT 0 5
INSERT 0 10
INSERT 0 8
CREATE ROLE
GRANT
GRANT
GRANT
ALTER DEFAULT PRIVILEGES

       status
-----------------------
 ✅ Database setup complete!
(1 row)

 table_name | record_count
------------+--------------
 Customers  |            5
 Orders     |           10
 Products   |           10
 Reviews    |            8
(4 rows)
```

### **Verify Data:**

```bash
# Check products
psql testdb -c "SELECT name, price FROM products LIMIT 3;"

# Check orders
psql testdb -c "SELECT COUNT(*) FROM orders;"

# Check reviews
psql testdb -c "SELECT COUNT(*) FROM reviews;"
```

**✅ Checkpoint:** Database has 10 products, 5 customers, 10 orders, and 8 reviews.

---

## **7. SETUP PYTHON ENVIRONMENT**

### **Create Project Directory:**

```bash
# Create project folder
mkdir -p ~/db-agent-test
cd ~/db-agent-test
```

### **Install Python Dependencies:**

```bash
# Install required packages
pip install langchain \
            langchain-openai \
            langchain-postgres \
            langchain-community \
            psycopg[binary] \
            sqlalchemy \
            python-dotenv
```

**Expected:** All packages install successfully.

### **Create Environment Variables File:**

```bash
# Create .env file
cat > .env << 'EOF'
# OpenAI API Key (REQUIRED - update this!)
OPENAI_API_KEY=sk-your-actual-openai-key-here

# PostgreSQL connection for main operations
DATABASE_URL=postgresql://localhost:5432/testdb

# Read-only connection for agent (security best practice)
READONLY_DATABASE_URL=postgresql://readonly_agent:agent123@localhost:5432/testdb
EOF
```

**⚠️ IMPORTANT:** Edit `.env` and replace `sk-your-actual-openai-key-here` with your real OpenAI API key!

```bash
# Edit .env file
nano .env  # or use your preferred editor (vim, code, etc.)
```

**✅ Checkpoint:** `.env` file exists with valid OpenAI API key.

---

## **8. CREATE APPLICATION FILES**

### **File 1: Ingestion Script (01_ingest.py)**

This script extracts text from the database and creates vector embeddings.

```bash
cat > 01_ingest.py << 'EOF'
"""
INGESTION SCRIPT
================
Extracts text-heavy columns from PostgreSQL database and creates vector embeddings.

What it does:
1. Connects to PostgreSQL database
2. Extracts product descriptions and reviews
3. Generates embeddings using OpenAI API
4. Stores embeddings in pgvector for semantic search

Run this: ONCE initially, then again when data changes
Cost: ~$0.01-0.05 per run (OpenAI embedding API)
"""

import os
from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from langchain_core.documents import Document
import psycopg

# Load environment variables from .env
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = "text_embeddings"

def extract_text_from_database():
    """
    Extract text-heavy columns from database tables.
    
    Returns:
        list[Document]: List of LangChain documents with text content and metadata
    """
    print("🔗 Connecting to database...")
    conn = psycopg.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    documents = []
    
    # ========================================================================
    # Extract Product Descriptions
    # ========================================================================
    print("📦 Extracting product descriptions...")
    cursor.execute("""
        SELECT 
            id,
            name,
            description,
            category,
            price
        FROM products
        WHERE description IS NOT NULL
    """)
    
    products = cursor.fetchall()
    for product_id, name, description, category, price in products:
        doc = Document(
            page_content=f"Product: {name}\n\nDescription: {description}",
            metadata={
                "id": str(product_id),
                "name": name,
                "category": category,
                "price": float(price),
                "source_table": "products",
                "type": "product_description"
            }
        )
        documents.append(doc)
    
    print(f"   ✓ Extracted {len(products)} product descriptions")
    
    # ========================================================================
    # Extract Reviews
    # ========================================================================
    print("⭐ Extracting reviews...")
    cursor.execute("""
        SELECT 
            r.id,
            r.product_id,
            r.review_text,
            r.rating,
            p.name
        FROM reviews r
        JOIN products p ON r.product_id = p.id
        WHERE r.review_text IS NOT NULL
    """)
    
    reviews = cursor.fetchall()
    for review_id, product_id, review_text, rating, product_name in reviews:
        doc = Document(
            page_content=f"Review for {product_name}:\n\n{review_text}",
            metadata={
                "id": str(review_id),
                "product_id": str(product_id),
                "product_name": product_name,
                "rating": rating,
                "source_table": "reviews",
                "type": "review"
            }
        )
        documents.append(doc)
    
    print(f"   ✓ Extracted {len(reviews)} reviews")
    
    cursor.close()
    conn.close()
    
    return documents


def create_embeddings(documents):
    """
    Generate embeddings and store in pgvector.
    
    Args:
        documents: List of Document objects to embed
    """
    total_docs = len(documents)
    
    # Estimate cost
    avg_tokens_per_doc = 150
    total_tokens = total_docs * avg_tokens_per_doc
    cost_per_million_tokens = 0.02  # text-embedding-3-small pricing
    estimated_cost = (total_tokens / 1_000_000) * cost_per_million_tokens
    
    print(f"\n📊 Ingestion Summary:")
    print(f"   Total documents: {total_docs}")
    print(f"   Estimated tokens: ~{total_tokens:,}")
    print(f"   Estimated cost: ~${estimated_cost:.4f}")
    
    print("\n🚀 Generating embeddings (this may take 10-30 seconds)...")
    
    # Use OpenAI's smaller, cheaper embedding model
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    
    # Create vector store in PostgreSQL
    vectorstore = PGVector.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name=VECTOR_COLLECTION,
        connection=DATABASE_URL,
        pre_delete_collection=True,  # Clear old embeddings
    )
    
    print(f"\n✅ Success! Created {total_docs} embeddings")
    print(f"   Collection name: {VECTOR_COLLECTION}")
    print(f"   Storage: PostgreSQL (pgvector)")


def main():
    """Main execution function."""
    print("=" * 70)
    print("DATABASE TO VECTOR INGESTION")
    print("=" * 70)
    print()
    
    try:
        # Step 1: Extract text from database
        documents = extract_text_from_database()
        
        if not documents:
            print("⚠️  No documents found to ingest!")
            return
        
        # Step 2: Create embeddings
        create_embeddings(documents)
        
        print("\n" + "=" * 70)
        print("✅ INGESTION COMPLETE!")
        print("=" * 70)
        print("\nNext step: Run the agent with 'python 02_agent.py'")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
EOF
```

### **File 2: Database Agent (02_agent.py)**

This is the main agent that answers questions using hybrid SQL + Vector search.

```bash
cat > 02_agent.py << 'EOF'
"""
DATABASE AGENT
==============
Hybrid Text-to-SQL + RAG agent for answering database questions.
"""

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector

# Load environment variables
load_dotenv()

# Configuration
READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = "text_embeddings"

# ============================================================================
# Custom Semantic Search Tool
# ============================================================================


def semantic_search_tool(query: str) -> str:
    """
    Search database text content by semantic similarity.
    
    Use for:
    - Finding by description: "products for gaming"
    - Similarity: "items like laptops"
    - Topic search: "reviews about battery"
    """
    try:
        docs = vectorstore.similarity_search(query, k=5)

        if not docs:
            return "No similar content found"

        results = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata
            content_preview = doc.page_content[:200]

            results.append(
                f"{i}. {meta.get('name', 'N/A')} [{meta.get('source_table', 'unknown')}]\n"
                f"   {content_preview}...\n"
                f"   (ID: {meta.get('id', 'N/A')})"
            )

        return "\n\n".join(results)

    except Exception as e:
        return f"❌ Error: {str(e)}"


# ============================================================================
# Setup: SQL Database
# ============================================================================

print("🔗 Connecting to SQL database...")
sql_db = SQLDatabase.from_uri(READONLY_DB_URL, sample_rows_in_table_info=2)
print("   ✓ SQL database connected")

# ============================================================================
# Setup: Vector Database
# ============================================================================

print("🔗 Connecting to vector database...")
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = PGVector(
    connection=DATABASE_URL, collection_name=VECTOR_COLLECTION, embeddings=embeddings,
)
print("   ✓ Vector database connected")

# ============================================================================
# Create AI Agent with Toolkit
# ============================================================================

print("🤖 Initializing AI agent...")

# Initialize LLM
llm = init_chat_model(
    "gpt-4o",  # or "gpt-4-turbo"
    model_provider="openai",
    temperature=0,  # Deterministic for database queries
)

# Create SQL toolkit (provides multiple SQL tools)
sql_toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)

# Get all tools from toolkit + add custom semantic search
all_tools = sql_toolkit.get_tools() + [semantic_search_tool]

system_prompt = """You are an expert database assistant with access to powerful tools:

**SQL Tools (from toolkit):**
- sql_db_query: Execute SELECT queries
- sql_db_schema: Get table structure
- sql_db_list_tables: List available tables
- sql_db_query_checker: Validate SQL syntax

**Custom Tools:**
- semantic_search_tool: Find content by description or meaning

**Decision Guide:**
- User asks "how many", "total", "average", "sum" → Use sql_db_query
- User asks "what tables", "schema" → Use sql_db_list_tables or sql_db_schema
- User asks "find products about X", "similar to Y" → Use semantic_search_tool
- User asks "top selling products like X" → Use BOTH:
  1. First, semantic_search_tool to find relevant product IDs
  2. Then, sql_db_query to get sales data and rank them

**Rules:**
- Check table schemas first if you're unsure about column names
- ALWAYS use sql_db_query for numerical operations
- ALWAYS use semantic_search_tool for descriptive/semantic queries
- You can use multiple tools in sequence for complex queries
- Provide clear, concise answers
"""

agent = create_agent(model=llm, tools=all_tools, system_prompt=system_prompt,)

print("   ✓ Agent ready")
print(f"   ✓ Loaded {len(all_tools)} tools")

# ============================================================================
# Main Interface
# ============================================================================


def ask_database(question: str) -> str:
    """Ask a question to the database agent."""
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        return result["messages"][-1].content
    except Exception as e:
        return f"❌ Error: {str(e)}"


def main():
    """Main interactive loop."""
    print("\n" + "=" * 70)
    print("DATABASE QUESTION ANSWERING AGENT")
    print("=" * 70)
    print("\n✨ Capabilities:")
    print("  ✓ SQL queries (counts, filters, joins, aggregations)")
    print("  ✓ Schema inspection (tables, columns)")
    print("  ✓ Semantic search (find by description)")
    print("  ✓ Hybrid queries (combine both approaches)")
    print("\n💡 Example questions:")
    print("  1. What tables are available?")
    print("  2. How many products are in stock?")
    print("  3. What's the total revenue from all orders?")
    print("  4. Find products good for gaming")
    print("  5. What are the top 3 best-selling products?")
    print("\nType 'quit', 'exit', or 'q' to exit")
    print("=" * 70 + "\n")

    while True:
        question = input("❓ Your question: ").strip()

        if question.lower() in ["quit", "exit", "q"]:
            print("\n👋 Goodbye!")
            break

        if not question:
            continue

        print("\n🤔 Thinking...\n")
        answer = ask_database(question)
        print(f"\n💡 Answer:\n{answer}\n")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
EOF
```

### **File 3: Quick Test Script (03_test.py)**

Automated test script to verify everything works.

```bash
cat > 03_test.py << 'EOF'
"""
QUICK TEST SCRIPT
=================
Runs automated tests to verify the agent is working correctly.

Usage:
    python 03_test.py
"""

import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector

load_dotenv()

READONLY_DB_URL = os.getenv("READONLY_DATABASE_URL")
DATABASE_URL = os.getenv("DATABASE_URL")
VECTOR_COLLECTION = "text_embeddings"

print("🔧 Setting up test environment...")

# ============================================================================
# Setup Databases
# ============================================================================

sql_db = SQLDatabase.from_uri(READONLY_DB_URL, sample_rows_in_table_info=2)
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = PGVector(
    connection=DATABASE_URL, collection_name=VECTOR_COLLECTION, embeddings=embeddings
)

# ============================================================================
# Define Custom Semantic Search Tool
# ============================================================================


def semantic_search_tool(query: str) -> str:
    """Search database text content by semantic similarity."""
    try:
        docs = vectorstore.similarity_search(query, k=3)
        if not docs:
            return "No similar content found"

        results = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata
            content_preview = doc.page_content[:150]
            results.append(
                f"{i}. {meta.get('name', 'N/A')} [{meta.get('source_table', 'unknown')}]\n"
                f"   {content_preview}..."
            )

        return "\n\n".join(results)
    except Exception as e:
        return f"❌ Error: {str(e)}"


# ============================================================================
# Create Agent (Modern LangChain API with Toolkit)
# ============================================================================

# Initialize LLM
llm = init_chat_model(
    "gpt-4o",
    model_provider="openai",
    temperature=0,  # Deterministic for database queries
)

# Create SQL toolkit (provides multiple SQL tools)
sql_toolkit = SQLDatabaseToolkit(db=sql_db, llm=llm)

# Get all tools from toolkit + add custom semantic search
all_tools = sql_toolkit.get_tools() + [semantic_search_tool]

system_prompt = """You are a database assistant with access to SQL and semantic search tools.

Use SQL tools (sql_db_query, sql_db_schema, sql_db_list_tables) for:
- Counts, sums, averages, totals
- Filtering by exact values
- Joining tables
- Schema inspection

Use semantic_search_tool for:
- Finding by description or meaning
- Similarity searches
- Topic-based searches

Provide clear, concise answers."""

agent = create_agent(
    model=llm,
    tools=all_tools,
    system_prompt=system_prompt,
)

print(f"   ✓ Test environment ready ({len(all_tools)} tools loaded)\n")

# ============================================================================
# Test Cases
# ============================================================================

test_cases = [
    {
        "name": "SQL Count Query",
        "question": "How many products are in the database?",
        "expected_type": "number",
    },
    {
        "name": "SQL Aggregation Query",
        "question": "What's the total revenue from all orders?",
        "expected_type": "number",
    },
    {
        "name": "Semantic Search - Products",
        "question": "Find products good for gaming",
        "expected_type": "list",
    },
    {
        "name": "Semantic Search - Reviews",
        "question": "Show me reviews mentioning battery",
        "expected_type": "text",
    },
    {
        "name": "Schema Inspection",
        "question": "What tables are available in the database?",
        "expected_type": "list",
    },
]

# ============================================================================
# Run Tests
# ============================================================================

print("=" * 70)
print("AUTOMATED AGENT TESTS")
print("=" * 70)

passed = 0
failed = 0

for i, test in enumerate(test_cases, 1):
    print(f"\n🧪 TEST {i}/{len(test_cases)}: {test['name']}")
    print(f"   Question: {test['question']}")
    print("-" * 70)

    try:
        # Invoke agent with new API
        result = agent.invoke(
            {"messages": [{"role": "user", "content": test["question"]}]}
        )

        # Extract answer from response
        answer = result["messages"][-1].content

        # Display result
        print(f"\n   ✅ Answer: {answer[:200]}")
        if len(answer) > 200:
            print(f"      ... (truncated, full length: {len(answer)} chars)")

        passed += 1

    except Exception as e:
        print(f"\n   ❌ FAILED: {str(e)}")
        failed += 1

# ============================================================================
# Summary
# ============================================================================

print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)
print(f"✅ Passed: {passed}/{len(test_cases)}")
print(f"❌ Failed: {failed}/{len(test_cases)}")

if failed == 0:
    print("\n🎉 All tests passed! The agent is working correctly.")
    print("\nNext step: Run interactive agent with 'python agent.py'")
else:
    print(f"\n⚠️  {failed} test(s) failed. Check error messages above.")

print("=" * 70)
EOF
```

**✅ Checkpoint:** Three Python files created: `01_ingest.py`, `02_agent.py`, `03_test.py`

---

## **9. RUN THE APPLICATION**

### **Step 1: Verify Setup**

```bash
# Ensure you're in the project directory
cd ~/db-agent-test

# Verify files exist
ls -la

# Expected files:
# .env
# 01_ingest.py
# 02_agent.py
# 03_test.py
```

### **Step 2: Update OpenAI API Key**

```bash
# Edit .env file and add your OpenAI API key
nano .env

# Replace: sk-your-actual-openai-key-here
# With: sk-proj-... (your actual key)

# Save and exit (Ctrl+X, Y, Enter in nano)
```

### **Step 3: Run Ingestion (ONE TIME)**

```bash
# Generate embeddings for text content
python 01_ingest.py
```

**Expected Output:**
```
======================================================================
DATABASE TO VECTOR INGESTION
======================================================================

🔗 Connecting to database...
📦 Extracting product descriptions...
   ✓ Extracted 10 product descriptions
⭐ Extracting reviews...
   ✓ Extracted 8 reviews

📊 Ingestion Summary:
   Total documents: 18
   Estimated tokens: ~2,700
   Estimated cost: ~$0.0001

🚀 Generating embeddings (this may take 10-30 seconds)...

✅ Success! Created 18 embeddings
   Collection name: text_embeddings
   Storage: PostgreSQL (pgvector)

======================================================================
✅ INGESTION COMPLETE!
======================================================================

Next step: Run the agent with 'python 02_agent.py'
```

**✅ Checkpoint:** Ingestion completed successfully, 18 embeddings created.

### **Step 4: Run Automated Tests**

```bash
# Run quick tests to verify everything works
python 03_test.py
```

**Expected:** All 4 tests should pass with answers.

### **Step 5: Run Interactive Agent**

```bash
# Start the interactive agent
python 02_agent.py
```

**Expected Output:**
```
🔗 Connecting to SQL database...
   ✓ SQL database connected
🔗 Connecting to vector database...
   ✓ Vector database connected
🤖 Initializing AI agent...
   ✓ Agent ready

======================================================================
DATABASE QUESTION ANSWERING AGENT
======================================================================

✨ Capabilities:
  ✓ SQL queries (counts, filters, joins, aggregations)
  ✓ Semantic search (find by description)
  ✓ Hybrid queries (combine both approaches)

💡 Example questions:
  1. How many products are in stock?
  2. What's the total revenue from all orders?
  3. Find products good for gaming
  4. What are the top 3 best-selling products?
  5. Show me reviews mentioning battery life

Type 'quit', 'exit', or 'q' to exit
======================================================================

❓ Your question: 
```

---

## **10. USAGE EXAMPLES**

### **Example 1: Count Query (SQL)**

```
❓ Your question: How many products are in the database?

🤔 Thinking...

> Entering new AgentExecutor chain...
[Agent uses SQLDatabase tool]
[Executes: SELECT COUNT(*) FROM products]

💡 Answer:
There are 10 products in the database.
```

### **Example 2: Aggregation Query (SQL)**

```
❓ Your question: What's the total revenue from all orders?

🤔 Thinking...

> Entering new AgentExecutor chain...
[Agent uses SQLDatabase tool]
[Executes: SELECT SUM(total_amount) FROM orders]

💡 Answer:
The total revenue from all orders is $6,619.87.
```

### **Example 3: Semantic Search (Vector)**

```
❓ Your question: Find products good for gaming

🤔 Thinking...

> Entering new AgentExecutor chain...
[Agent uses SemanticSearch tool]

💡 Answer:
Here are products good for gaming:
1. Gaming Laptop Pro X1 - High-performance gaming laptop with RTX 4080...
2. Wireless Gaming Mouse - Ergonomic mouse with 16000 DPI sensor...
3. Mechanical Keyboard RGB - Premium mechanical keyboard...
```

### **Example 4: Hybrid Query (SQL + Vector)**

```
❓ Your question: What are the top 3 best-selling products related to laptops?

🤔 Thinking...

> Entering new AgentExecutor chain...
[Agent uses SemanticSearch to find laptop product IDs]
[Agent uses SQLDatabase to get order counts]

💡 Answer:
Top 3 best-selling laptop-related products:
1. Gaming Laptop Pro X1 - 2 orders
2. UltraBook Air M2 - 1 order
3. 4K Monitor 32" - 1 order
```

### **Example 5: Review Search (Vector)**

```
❓ Your question: Show me reviews about battery life

🤔 Thinking...

> Entering new AgentExecutor chain...
[Agent uses SemanticSearch tool]

💡 Answer:
Here are reviews mentioning battery life:
1. "Lightweight and perfect for travel. Battery life is amazing..."
2. "Camera quality is outstanding! Battery easily lasts a full day..."
3. "Premium wireless headphones with 30-hour battery life..."
```

---

## **11. TROUBLESHOOTING**

### **Issue: `psql: command not found`**

**Solution:**
```bash
# Re-add to PATH
echo 'export PATH="/usr/local/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### **Issue: `createdb: database creation failed`**

**Solution:**
```bash
# Create PostgreSQL user first
createuser -s $(whoami)
createdb testdb
```

### **Issue: `CREATE EXTENSION vector failed`**

**Solution:**
```bash
# Reinstall pgvector
brew reinstall pgvector

# Try enabling again
psql testdb -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### **Issue: `psycopg2 connection error`**

**Solution:**
```bash
# Check if PostgreSQL is running
brew services list | grep postgresql@15

# If stopped, start it
brew services start postgresql@15

# Wait 5 seconds and try again
```

### **Issue: `OpenAI API key not found`**

**Solution:**
```bash
# Verify .env file has the key
cat .env | grep OPENAI_API_KEY

# If missing or wrong, edit it
nano .env
```

### **Issue: `No module named 'langchain'`**

**Solution:**
```bash
# Reinstall dependencies
pip install --upgrade langchain langchain-openai langchain-postgres langchain-community psycopg[binary] sqlalchemy python-dotenv
```

### **Issue: Agent gives wrong answers**

**Solution:**
```bash
# Re-run ingestion to refresh embeddings
python 01_ingest.py

# Try again
python 02_agent.py
```

---

## **12. CLEANUP**

### **Stop Services:**

```bash
# Stop PostgreSQL
brew services stop postgresql@15
```

### **Remove Database:**

```bash
# Drop database
dropdb testdb

# Drop readonly user
psql postgres -c "DROP USER IF EXISTS readonly_agent;"
```

### **Remove Project:**

```bash
# Remove project folder
rm -rf ~/db-agent-test

# Remove SQL file
rm ~/create_schema.sql
```

### **Uninstall Software (Optional):**

```bash
# Uninstall PostgreSQL
brew uninstall postgresql@15

# Uninstall pgvector
brew uninstall pgvector

# Remove from PATH
sed -i '' '/postgresql@15/d' ~/.zshrc
source ~/.zshrc
```

---

## **APPENDIX**

### **A. Database Schema**

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│  products   │      │  customers  │      │   orders    │
├─────────────┤      ├─────────────┤      ├─────────────┤
│ id          │◄─────┤ id          │◄─────┤ id          │
│ name        │      │ name        │      │ customer_id │
│ description │      │ email       │      │ product_id  │
│ category    │      │ city        │      │ quantity    │
│ price       │      │ country     │      │ total_amount│
│ stock_qty   │      └─────────────┘      │ order_date  │
└─────────────┘                           │ status      │
      ▲                                   └─────────────┘
      │
      │
┌─────────────┐
│   reviews   │
├─────────────┤
│ id          │
│ product_id  │
│ customer_id │
│ review_text │
│ rating      │
└─────────────┘
```

### **B. Architecture**

```
User Question
     │
     ▼
┌─────────────────────────────────┐
│  AI Agent (GPT-4)               │
│  - Analyzes question            │
│  - Chooses appropriate tool(s)  │
└─────────────────────────────────┘
     │
     ├─────────────────┬─────────────────┐
     ▼                 ▼                 ▼
┌──────────┐    ┌──────────┐    ┌──────────┐
│ SQL Tool │    │Vector DB │    │   Both   │
│          │    │   Tool   │    │  Tools   │
└──────────┘    └──────────┘    └──────────┘
     │                 │                 │
     ▼                 ▼                 ▼
┌─────────────────────────────────────────┐
│  PostgreSQL Database                    │
│  ┌──────────────┐  ┌─────────────────┐ │
│  │ Tables       │  │ Vector Store    │ │
│  │ (structured) │  │ (embeddings)    │ │
│  └──────────────┘  └─────────────────┘ │
└─────────────────────────────────────────┘
     │
     ▼
  Answer
```

### **C. Cost Breakdown**

| Component | One-time Cost | Monthly Cost (estimated) |
|-----------|---------------|--------------------------|
| PostgreSQL | Free (local) | $0 |
| pgvector | Free (open source) | $0 |
| OpenAI Embeddings | ~$0.01-0.05 | ~$0.10-0.50 (if re-indexing) |
| OpenAI GPT-4 API | N/A | ~$5-20 (depends on usage) |
| **Total** | **~$0.05** | **~$5-20** |

**Notes:**
- Embeddings: Created once, updated only when data changes
- GPT-4: Charged per question asked (~$0.01-0.05 per question)
- Much cheaper than managed vector databases like Pinecone ($70+/month)

---

## **SUMMARY**

✅ **What You Built:**
- PostgreSQL database with sample e-commerce data
- pgvector extension for semantic search
- Hybrid AI agent combining SQL + Vector search
- Secure read-only access for queries
- Interactive chat interface

✅ **What You Can Do:**
- Ask questions about your database in natural language
- Get counts, sums, averages (SQL)
- Find items by description (Vector search)
- Complex queries using both approaches

✅ **Next Steps:**
- Add your own database schema
- Customize the ingestion script for your tables
- Add more complex queries
- Deploy to production

---

**Questions?** Review the troubleshooting section or ask for help!