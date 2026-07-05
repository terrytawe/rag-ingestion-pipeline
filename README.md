# Ingestion Pipeline

This project ingests local documents into Chroma for retrieval-augmented generation (RAG).

## Supported Inputs

- PDF (`.pdf`)
- Word (`.docx`)
- Text (`.txt`)
- Markdown (`.md`)

## Image-Aware PDF Ingestion

PDF ingestion uses `PyMuPDFLoader` with `extract_images=True`.
That means image-heavy or scanned PDFs can contribute OCR text to your vector store,
instead of being silently skipped as "non-text" content.

If OCR dependencies are unavailable, ingestion falls back to text-only PDF extraction.

## Visual Understanding (Charts/Diagrams)

In addition to OCR extraction, ingestion can run a second pass on PDF pages that contain images.
This pass sends page renders to Anthropic and stores concise "image_summary" chunks so your
retriever can answer chart/diagram questions better.

Environment variables:

```bash
export ANTHROPIC_API_KEY=your_key_here
export ENABLE_PDF_IMAGE_SUMMARIES=true
export IMAGE_SUMMARY_MODEL=claude-sonnet-5
export MAX_IMAGE_SUMMARY_PAGES=12
```

If `ANTHROPIC_API_KEY` is not set, the image-summary pass is skipped safely.

## Retrieval Tuning

Query-time retrieval now uses MMR by default for better diversity and recall:

- `search_type=mmr`
- `k=8`
- `fetch_k=24`
- `lambda_mult=0.3`

This generally improves answers for broad questions that need evidence from multiple sections.

## Install

Using uv:

```bash
uv sync
```

Using pip:

```bash
pip install -r requirements.txt
```

## Reindex After Pipeline Changes

Because extraction behavior changed, do a clean re-ingest to avoid stale vectors:

```bash
rm -rf chroma_db manifest.json
uv run ingest.py
```

Then query:

```bash
uv run main.py
```

## Reset / Reinitialize RAG

Use the reset utility to clear local vector state:

```bash
uv run reset_rag.py
```

Useful flags:

```bash
# Skip prompt
uv run reset_rag.py --force

# Clear and immediately rebuild vectors
uv run reset_rag.py --force --rebuild
```

Answers now include block citations like `[1]`, `[2]` that map to context blocks
containing source path, page number, and modality.
