"""
Shared configuration for the ingestion and query pipelines.

Both scripts must agree on the embedding model, persist directory, and
collection name. If these drift apart, Chroma will not raise an error,
it will just return meaningless matches, because the query vector and
the stored vectors no longer live in a comparable space.
"""

import os
from pathlib import Path

SOURCE_FOLDER = Path("./documents")
CHROMA_DIR = Path("./chroma_db")
MANIFEST_PATH = Path("./manifest.json")
COLLECTION_NAME = "documents"
EMBEDDING_MODEL = "qwen3-embedding:latest"

# Retrieval quality defaults.
RETRIEVAL_SEARCH_TYPE = "mmr"
RETRIEVAL_K = 8
RETRIEVAL_FETCH_K = 24
RETRIEVAL_LAMBDA_MULT = 0.3

# Optional second-pass image/diagram understanding for PDF pages.
# Requires ANTHROPIC_API_KEY and outbound network access at ingest time.
ENABLE_PDF_IMAGE_SUMMARIES = os.getenv("ENABLE_PDF_IMAGE_SUMMARIES", "true").lower() == "true"
IMAGE_SUMMARY_MODEL = os.getenv("IMAGE_SUMMARY_MODEL", "claude-sonnet-5")
MAX_IMAGE_SUMMARY_PAGES = int(os.getenv("MAX_IMAGE_SUMMARY_PAGES", "12"))
