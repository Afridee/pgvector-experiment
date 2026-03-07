"""
INGESTION SCRIPT
================
Extracts text-heavy columns from PostgreSQL database and creates vector embeddings.

Updated behavior (QMR knowledge ingest):
1. Reads QMR semantic knowledge chunks from a .txt file (generated from code analysis)
2. Creates one LangChain Document per chunk with rich metadata (title, tags)
3. Generates embeddings using OpenAI API
4. Stores embeddings in pgvector for semantic search

Run this: ONCE initially, then again when knowledge changes
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres.vectorstores import PGVector

# Load environment variables from .env
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL")

# Use a dedicated collection for QMR knowledge chunks
VECTOR_COLLECTION = os.getenv("VECTOR_COLLECTION", "qmr_knowledge_chunks")

# Path to the chunks file (defaults to the file name produced earlier)
CHUNKS_FILE = os.getenv("CHUNKS_FILE", "knowledge_chunks.txt")


# ----------------------------
# Parsing helpers
# ----------------------------
_CHUNK_SPLIT_RE = re.compile(r"(?m)^\s*---\s*$")


def _parse_chunk_fields(chunk_text: str) -> dict:
    """
    Parse a single chunk of the form:

    title: ...
    tags: ...
    content:
    ...

    Returns a dict with keys: title (str|None), tags (list[str]), content (str).
    """
    # Normalize and trim
    raw = chunk_text.strip()
    if not raw:
        return {"title": None, "tags": [], "content": ""}

    title = None
    tags = []
    content = ""

    # Extract title
    m = re.search(r"(?m)^\s*title:\s*(.+?)\s*$", raw)
    if m:
        title = m.group(1).strip()

    # Extract tags
    m = re.search(r"(?m)^\s*tags:\s*(.+?)\s*$", raw)
    if m:
        tags_raw = m.group(1).strip()
        if tags_raw:
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    # Extract content (everything after the first "content:" line)
    m = re.search(r"(?ms)^\s*content:\s*\n(.*)$", raw)
    if m:
        content = m.group(1).strip()
    else:
        # Fallback: if content: marker is missing, keep remaining text
        content = raw

    return {"title": title, "tags": tags, "content": content}


def load_qmr_knowledge_documents(file_path: str) -> list[Document]:
    """
    Load QMR semantic knowledge chunks from a .txt file.

    Each chunk becomes one Document:
      - page_content: "Title: ...\nTags: ...\n\n<content>"
      - metadata: {source_file, type, title, tags, chunk_index}
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"QMR chunks file not found: {path.resolve()}\n"
            f"Set env var CHUNKS_FILE to the correct path."
        )

    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []

    # Split on lines that are exactly '---'
    # The file format uses '---' as both start and end separators, so splitting will
    # produce some empty segments which we filter out.
    parts = [p.strip() for p in _CHUNK_SPLIT_RE.split(text) if p.strip()]

    documents: list[Document] = []
    for idx, part in enumerate(parts, start=1):
        fields = _parse_chunk_fields(part)
        title = fields["title"] or f"QMR Knowledge Chunk {idx}"
        tags = fields["tags"]
        content = fields["content"]

        page_content = (
            f"Title: {title}\n"
            f"Tags: {', '.join(tags) if tags else ''}\n\n"
            f"{content}"
        ).strip()

        doc = Document(
            page_content=page_content,
            metadata={
                "type": "qmr_rule_chunk",
                "source_file": str(path.name),
                "source_path": str(path.resolve()),
                "chunk_index": idx,
                "title": title,
                "tags": tags,  # keep as list for structured filtering in app logic
            },
        )
        documents.append(doc)

    return documents


def create_embeddings(documents: list[Document]) -> None:
    """
    Generate embeddings and store in pgvector.

    Args:
        documents: List of Document objects to embed
    """
    total_docs = len(documents)

    # Estimate cost (rough)
    avg_tokens_per_doc = 250
    total_tokens = total_docs * avg_tokens_per_doc
    cost_per_million_tokens = 0.02  # text-embedding-3-small pricing (example)
    estimated_cost = (total_tokens / 1_000_000) * cost_per_million_tokens

    print(f"\n📊 Ingestion Summary:")
    print(f"   Total documents: {total_docs}")
    print(f"   Estimated tokens: ~{total_tokens:,}")
    print(f"   Estimated cost: ~${estimated_cost:.4f}")

    print("\n🚀 Generating embeddings (this may take some seconds)...")

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    # Create vector store in PostgreSQL
    PGVector.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name=VECTOR_COLLECTION,
        connection=DATABASE_URL,
        pre_delete_collection=True,  # Clear old embeddings (rebuild knowledge base)
    )

    print(f"\n✅ Success! Created {total_docs} embeddings")
    print(f"   Collection name: {VECTOR_COLLECTION}")
    print(f"   Storage: PostgreSQL (pgvector)")


def main():
    """Main execution function."""
    print("=" * 70)
    print("QMR KNOWLEDGE (.TXT) TO VECTOR INGESTION")
    print("=" * 70)
    print()

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set. Add it to your .env file.")

    try:
        print(f"📄 Loading QMR knowledge chunks from: {CHUNKS_FILE}")
        documents = load_qmr_knowledge_documents(CHUNKS_FILE)

        if not documents:
            print("⚠️  No knowledge chunks found to ingest!")
            return

        print(f"   ✓ Loaded {len(documents)} knowledge chunks")

        create_embeddings(documents)

        print("\n" + "=" * 70)
        print("✅ INGESTION COMPLETE!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
