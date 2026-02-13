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

import psycopg2
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector

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
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    documents = []

    # ========================================================================
    # Extract Product Descriptions
    # ========================================================================
    print("📦 Extracting product descriptions...")
    cursor.execute(
        """
        SELECT 
            id,
            name,
            description,
            category,
            price
        FROM products
        WHERE description IS NOT NULL
    """
    )

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
                "type": "product_description",
            },
        )
        documents.append(doc)

    print(f"   ✓ Extracted {len(products)} product descriptions")

    # ========================================================================
    # Extract Reviews
    # ========================================================================
    print("⭐ Extracting reviews...")
    cursor.execute(
        """
        SELECT 
            r.id,
            r.product_id,
            r.review_text,
            r.rating,
            p.name
        FROM reviews r
        JOIN products p ON r.product_id = p.id
        WHERE r.review_text IS NOT NULL
    """
    )

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
                "type": "review",
            },
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
