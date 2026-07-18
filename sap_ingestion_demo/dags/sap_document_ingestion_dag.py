"""
sap_document_ingestion_dag.py

Airflow 3.x DAG (TaskFlow API). Simulates ingesting SharePoint-hosted SAP
documents (CPPR, CPS), tagging each chunk with SAP authorisation metadata,
and upserting into ChromaDB.

The local folder ~/sap_sharepoint_sim stands in for the SharePoint document
library. manifest.csv stands in for SharePoint's custom metadata columns.
In production this step is a Microsoft Graph API call against the drive
item's listItem fields, not a local CSV read.

Deliberately OUT OF SCOPE for this DAG: live transactional SAP data (for
example, project status pulled at query time). That data is never
pre-ingested here, it is fetched on demand through the MCP Gateway Adapter
at query time. Embedding it into this batch pipeline would reintroduce the
staleness problem the dual-lane design exists to avoid.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pendulum
from airflow.sdk import dag, task
from airflow.exceptions import AirflowSkipException

DATASTORE_ROOT = Path.home() / "sap_sharepoint_sim"
MANIFEST_PATH = DATASTORE_ROOT / "manifest.csv"
CHROMA_PERSIST_DIR = Path.home() / "chroma_store"
CHROMA_COLLECTION = "sap_documents"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# Each entry here is a distinct simulated source. Adding a new document type
# later (a third SharePoint library, say) means adding one line here and one
# folder on disk, nothing else in the DAG changes.
DOC_TYPE_FOLDERS = {
    "CPPR": DATASTORE_ROOT / "cppr",
    "CPS": DATASTORE_ROOT / "cps",
}


@dag(
    dag_id="sap_document_ingestion",
    schedule="*/10 * * * *",  # every 10 minutes, tight enough to demo live during a viva
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["rag", "sap", "ingestion"],
)
def sap_document_ingestion():

    @task
    def load_manifest() -> list[dict]:
        """Stand-in for a SharePoint Graph API metadata call."""
        if not MANIFEST_PATH.exists():
            raise FileNotFoundError(f"Manifest not found at {MANIFEST_PATH}")
        with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            raise AirflowSkipException("Manifest is empty, nothing to ingest")
        return rows

    @task
    def fetch_document_batch(manifest_rows: list[dict]) -> list[dict]:
        """Resolve each manifest row to its file content, branching by doc_type folder."""
        resolved = []
        for row in manifest_rows:
            doc_type = row["doc_type"]
            folder = DOC_TYPE_FOLDERS.get(doc_type)
            if folder is None:
                continue  # unknown doc_type: skip this row rather than fail the whole batch
            file_path = folder / row["filename"]
            if not file_path.exists():
                continue
            resolved.append({
                "filename": row["filename"],
                "doc_type": doc_type,
                "bukrs": row.get("bukrs", "").strip(),
                "vkorg": row.get("vkorg", "").strip(),
                "actvt": row.get("actvt", "").strip(),
                "title": row.get("title", ""),
                "text": file_path.read_text(encoding="utf-8"),
            })
        return resolved

    @task
    def map_to_sap_auth_objects(documents: list[dict]) -> list[dict]:
        """
        Normalise auth fields. A production version would validate BUKRS and
        VKORG against a live SAP authorisation object list here. This POC
        trusts the manifest as ground truth.
        """
        tagged = []
        for doc in documents:
            auth_metadata = {
                "bukrs": doc["bukrs"] or None,
                "vkorg": doc["vkorg"] or None,
                "actvt": doc["actvt"] or "03",
            }
            tagged.append({**doc, "auth_metadata": auth_metadata})
        return tagged

    @task
    def chunk_documents(documents: list[dict]) -> list[dict]:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
        )
        chunks = []
        for doc in documents:
            pieces = splitter.split_text(doc["text"])
            for i, piece in enumerate(pieces):
                # Deterministic id: filename + chunk index. Reruns overwrite
                # the same Chroma record instead of creating duplicates,
                # which is what makes this DAG safe to rerun or backfill.
                chunk_id = hashlib.sha256(f"{doc['filename']}_{i}".encode()).hexdigest()[:16]
                chunks.append({
                    "chunk_id": chunk_id,
                    "text": piece,
                    "filename": doc["filename"],
                    "doc_type": doc["doc_type"],
                    "title": doc["title"],
                    **doc["auth_metadata"],
                })
        return chunks

    @task
    def embed_and_upsert(chunks: list[dict]) -> int:
        """
        Embedding and upsert are combined deliberately in one task.
        Embedding vectors are not small, and passing them between tasks
        through XCom (Airflow's metadata-database-backed data passing
        mechanism) is the wrong tool for that volume of data. Compute and
        persist in the same task instead of returning vectors as a XCom
        payload.
        """
        import chromadb
        import ollama

        client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
        collection = client.get_or_create_collection(CHROMA_COLLECTION)

        ids, texts, metadatas, embeddings = [], [], [], []
        for chunk in chunks:
            response = ollama.embeddings(model="qwen3-embedding", prompt=chunk["text"])
            ids.append(chunk["chunk_id"])
            texts.append(chunk["text"])
            embeddings.append(response["embedding"])
            metadatas.append({
                "filename": chunk["filename"],
                "doc_type": chunk["doc_type"],
                "title": chunk["title"],
                "bukrs": chunk["bukrs"],
                "vkorg": chunk["vkorg"],
                "actvt": chunk["actvt"],
            })

        collection.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)
        return len(ids)

    @task
    def validate_ingestion(chunk_count: int) -> None:
        if chunk_count == 0:
            raise AirflowSkipException("No chunks ingested this run")
        print(f"Ingested {chunk_count} chunks this run")

    manifest_rows = load_manifest()
    documents = fetch_document_batch(manifest_rows)
    tagged_documents = map_to_sap_auth_objects(documents)
    chunks = chunk_documents(tagged_documents)
    chunk_count = embed_and_upsert(chunks)
    validate_ingestion(chunk_count)


sap_document_ingestion()
