# Local Airflow Ingestion Demo: Setup and Walkthrough

What this demonstrates: a scheduled Airflow DAG that treats a local folder as
a stand-in for a SharePoint document library, tags each chunk with SAP
authorisation metadata (BUKRS, VKORG, ACTVT), and upserts into ChromaDB.
Two document types (CPPR, CPS) are ingested from separate simulated sources
in the same DAG run.

Written against Airflow 3.x. Check
https://airflow.apache.org/docs/apache-airflow/stable/start.html before you
run this, in case a newer version has shipped since this was written, and
swap the version number below accordingly.

---

## 0. Prerequisites

- `uv` installed (https://docs.astral.sh/uv/getting-started/installation/)
- Python 3.11 or 3.12 (Airflow 3.2+ supports 3.10 through 3.14, but
  chromadb and the Ollama client are safest on 3.11/3.12)
- Ollama installed and running, with the embedding model pulled:

```bash
ollama pull qwen3-embedding
```

If you installed the Ollama desktop app it is already running in the
background. Otherwise start it manually in its own terminal:

```bash
ollama serve
```

---

## 1. Set AIRFLOW_HOME and install Airflow

Set this before installing, so Airflow writes its files to your project
folder rather than the default `~/airflow`:

```bash
export AIRFLOW_HOME=~/sap_ingestion_demo/airflow_home
```

Install Airflow with the version-matched constraints file. This is the
officially documented method and avoids the dependency resolution problems
Airflow is notorious for:

```bash
AIRFLOW_VERSION=3.3.0
PYTHON_VERSION="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

uv pip install "apache-airflow==${AIRFLOW_VERSION}" --constraint "${CONSTRAINT_URL}"
```

## 2. Install the extra packages this DAG needs

These are not part of Airflow's own dependency tree, so they install
cleanly without the constraints file:

```bash
uv pip install -r requirements.txt
```

## 3. Put the DAG and the simulated datastore in place

```bash
mkdir -p "$AIRFLOW_HOME/dags"
cp dags/sap_document_ingestion_dag.py "$AIRFLOW_HOME/dags/"
cp -r sap_sharepoint_sim ~/sap_sharepoint_sim
```

The DAG reads from `~/sap_sharepoint_sim`, not from the Airflow project
folder, because in the real system this will eventually be replaced by a
SharePoint API call rather than a local path. Keeping it outside
`AIRFLOW_HOME` now makes that swap a one-line change later (replace the
`Path.home() / "sap_sharepoint_sim"` constant with a Graph API client call).

## 4. Run Airflow

```bash
airflow standalone
```

This single command initialises the metadata database, creates an admin
user, and starts every Airflow 3.x component (API server, scheduler,
DAG processor, triggerer) needed for local use. Your admin password is
printed to the terminal on first run.

Visit `localhost:8080`, log in, find `sap_document_ingestion` in the DAG
list, and un-pause it.

## 5. Trigger it and check the result

Don't wait ten minutes for the schedule. Trigger it manually the first
time:

```bash
airflow dags trigger sap_document_ingestion
```

Watch the run in the UI, or tail it from the CLI:

```bash
airflow dags list-runs -d sap_document_ingestion
```

Confirm the chunks landed in Chroma:

```bash
python3 -c "
import chromadb
client = chromadb.PersistentClient(path='$HOME/chroma_store')
collection = client.get_or_create_collection('sap_documents')
print(collection.count(), 'chunks stored')
print(collection.get(limit=3))
"
```

## 6. Test the tagging by trying it again with a new file

Drop a new `.txt` file into `~/sap_sharepoint_sim/cppr/` or `.../cps/`, add
a matching row to `~/sap_sharepoint_sim/manifest.csv`, and either wait for
the next scheduled run or trigger manually again. Because chunk IDs are
derived deterministically from filename and chunk index, reruns overwrite
existing records rather than duplicating them, this is what makes the DAG
safe to rerun or backfill.

---

## Design notes carried over from the architecture diagrams

- **Why this DAG stops at two sources.** CPPR and CPS are the two document
  types already established for the static ingestion lane. Live
  transactional data (project status, and similar) is deliberately excluded
  from this DAG. It is fetched at query time through the MCP Gateway
  Adapter instead, never pre-ingested, because embedding fast-changing
  records here would reintroduce the staleness problem the dual-lane split
  exists to solve. If you find yourself wanting to add a "live data" task
  to this DAG, that is a sign the lane boundary is being violated, not a
  sign this DAG is incomplete.
- **Schedule choice.** `*/10 * * * *` is set tight for demo purposes, so you
  can drop a file in and see it appear within ten minutes without manually
  triggering every time. For a real SharePoint source, polling on a
  schedule is a reasonable starting point, but a Graph API change
  notification webhook or delta query is the better long-term design, poll
  intervals are a proxy for "I don't have an event feed yet."
  Cache-miss fallback and hierarchy flattening open questions carried from
  the ingestion tagging step are unaffected by this choice either way.
- **Embedding and upsert share one task.** This is not a style choice, it
  is because XCom (how Airflow passes data between tasks) is backed by the
  metadata database and is not meant to carry large payloads like embedding
  vectors for many chunks. Keeping embedding and upsert in the same task
  avoids ever writing a vector to XCom.
