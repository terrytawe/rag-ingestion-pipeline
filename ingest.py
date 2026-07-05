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
import base64
import os
from urllib import error as urlerror
from urllib import request as urlrequest
from pathlib import Path

import fitz
from langchain_community.document_loaders import (
    PyMuPDFLoader,
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
)
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

from config import (
    SOURCE_FOLDER,
    CHROMA_DIR,
    MANIFEST_PATH,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    ENABLE_PDF_IMAGE_SUMMARIES,
    IMAGE_SUMMARY_MODEL,
    MAX_IMAGE_SUMMARY_PAGES,
)

# --- Configuration ---

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

LOADER_MAP = {
    ".pdf": PyMuPDFLoader, # changed from PyPDFLoader to PyMuPDFLoader for better image extraction
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


def summarize_pdf_page_image(image_png_bytes: bytes) -> str | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    image_b64 = base64.b64encode(image_png_bytes).decode("ascii")
    payload = {
        "model": IMAGE_SUMMARY_MODEL,
        "max_tokens": 220,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Summarize only concrete, visible facts in this PDF page image. "
                            "Prioritize chart trends, table values, labels, legends, and diagram relationships. "
                            "If uncertain, say so briefly."
                        ),
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                ],
            }
        ],
    }

    req = urlrequest.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urlerror.URLError, TimeoutError, json.JSONDecodeError):
        return None

    content = body.get("content", [])
    texts = [block.get("text", "").strip() for block in content if block.get("type") == "text"]
    combined = " ".join([text for text in texts if text]).strip()
    return combined or None


def extract_pdf_image_summary_docs(path: Path, rel_path: str) -> list[Document]:
    if not ENABLE_PDF_IMAGE_SUMMARIES:
        return []

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("  warn: skipping image summaries (ANTHROPIC_API_KEY not set)")
        return []

    docs: list[Document] = []
    processed_pages = 0
    pdf = fitz.open(str(path))

    try:
        for page_idx in range(pdf.page_count):
            if processed_pages >= MAX_IMAGE_SUMMARY_PAGES:
                break

            page = pdf.load_page(page_idx)
            if not page.get_images(full=True):
                continue

            pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            summary = summarize_pdf_page_image(pix.tobytes("png"))
            processed_pages += 1

            if not summary:
                continue

            docs.append(
                Document(
                    page_content=f"Image/diagram summary: {summary}",
                    metadata={
                        "source_path": rel_path,
                        "page": page_idx,
                        "modality": "image_summary",
                    },
                )
            )
    finally:
        pdf.close()

    return docs


# --- Load and split ---

def load_and_split(rel_path: str):
    path = SOURCE_FOLDER / rel_path
    suffix = path.suffix.lower()
    loader_cls = LOADER_MAP[suffix]

    if suffix == ".pdf":
        try:
            # extract_images=True uses OCR for image-only/scanned PDF regions
            # when rapidocr dependencies are installed.
            loader = loader_cls(str(path), extract_images=True)
        except Exception as exc:
            print(f"  warn: falling back to text-only PDF loader for {rel_path} ({exc})")
            loader = PyPDFLoader(str(path))
    else:
        loader = loader_cls(str(path))

    docs = loader.load()

    if suffix == ".pdf":
        docs.extend(extract_pdf_image_summary_docs(path, rel_path))

    for doc in docs:
        doc.metadata["source_path"] = rel_path
        doc.metadata.setdefault("modality", "text")

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
