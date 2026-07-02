"""
Shared configuration for the ingestion and query pipelines.

Both scripts must agree on the embedding model, persist directory, and
collection name. If these drift apart, Chroma will not raise an error,
it will just return meaningless matches, because the query vector and
the stored vectors no longer live in a comparable space.
"""

from pathlib import Path

SOURCE_FOLDER = Path("./documents")
CHROMA_DIR = Path("./chroma_db")
MANIFEST_PATH = Path("./manifest.json")
COLLECTION_NAME = "documents"
EMBEDDING_MODEL = "qwen3-embedding:latest "
