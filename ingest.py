"""
Simple RAG ingestion pipeline.

Scans a local folder of documents (pdf, docx, txt, md) and ingests new or
changed files into a local Chroma vector store, using Ollama for embeddings.

This is a one-shot script, not a resident process. Run it periodically
via cron, launchd, or Windows Task Scheduler. A JSON manifest tracks file
hashes so unchanged files are skipped on subsequent runs.
"""

import hashlib
import json
from pathlib import Path

from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

from config import SOURCE_FOLDER, CHROMA_DIR, MANIFEST_PATH, COLLECTION_NAME, EMBEDDING_MODEL

# --- Configuration ---

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

LOADER_MAP = {
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
}


# --- Manifest handling ---

def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Discovery ---

def discover_files() -> dict:
    """Return {relative_path: hash} for every supported file currently in the folder."""
    files = {}
    for path in SOURCE_FOLDER.rglob("*"):
        if path.is_file() and path.suffix.lower() in LOADER_MAP:
            rel = str(path.relative_to(SOURCE_FOLDER))
            files[rel] = file_hash(path)
    return files


def diff_manifest(current: dict, previous: dict):
    """Return (new_files, changed_files, removed_files) as relative path lists."""
    new_files = [f for f in current if f not in previous]
    changed_files = [f for f in current if f in previous and current[f] != previous[f]]
    removed_files = [f for f in previous if f not in current]
    return new_files, changed_files, removed_files


# --- Load and split ---

def load_and_split(rel_path: str):
    path = SOURCE_FOLDER / rel_path
    loader_cls = LOADER_MAP[path.suffix.lower()]
    loader = loader_cls(str(path))
    docs = loader.load()

    for doc in docs:
        doc.metadata["source_path"] = rel_path

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_documents(docs)


# --- Main ingestion run ---

def main():
    SOURCE_FOLDER.mkdir(exist_ok=True)

    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
    )

    previous_manifest = load_manifest()
    current_manifest = discover_files()
    new_files, changed_files, removed_files = diff_manifest(current_manifest, previous_manifest)

    print(f"New: {len(new_files)}  Changed: {len(changed_files)}  Removed: {len(removed_files)}")

    # Remove existing vectors for changed or deleted files before re-adding.
    for rel_path in changed_files + removed_files:
        vectorstore.delete(where={"source_path": rel_path})

    # Ingest new and changed files.
    for rel_path in new_files + changed_files:
        try:
            chunks = load_and_split(rel_path)
            if chunks:
                vectorstore.add_documents(chunks)
            print(f"  ingested: {rel_path} ({len(chunks)} chunks)")
        except Exception as exc:
            print(f"  failed: {rel_path} ({exc})")
            current_manifest.pop(rel_path, None)  # retry this file on next run

    save_manifest(current_manifest)
    print("Done.")


if __name__ == "__main__":
    main()
