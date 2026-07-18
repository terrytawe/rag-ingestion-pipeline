# Enterprise RAG — Sequence Diagrams

Two diagrams covering the two distinct flows in the system.

- **Diagram 1** covers the background ingestion pipeline that populates the vector index from internal documents and SharePoint. This runs on a schedule, not per user request.
- **Diagram 2** covers the per-request query flow, showing how a single user query fans out across all three data sources under a unified auth envelope.

---

## Diagram 1 — Ingestion pipeline (background, scheduled via Airflow)

This is the pattern adapted for enterprise sources.
No user is involved. Airflow triggers it on a schedule.
Auth metadata is stamped onto documents at ingestion time, not at query time.

```mermaid
sequenceDiagram
    autonumber

    participant Airflow as Airflow DAG<br/>(Scheduler)
    participant DocStore as Internal document store<br/>(file server / NAS)
    participant SPGraph as SharePoint<br/>(Microsoft Graph API)
    participant Parser as Document parser<br/>(Docling / pdfplumber)
    participant Chunker as Chunking engine
    participant Embedder as Embedding model<br/>(local, via Ollama)
    participant PG as PostgreSQL<br/>(metadata store)
    participant OS as OpenSearch<br/>(vector + keyword index)

    Note over Airflow: Scheduled trigger — e.g. nightly at 02:00

    Airflow->>DocStore: List files modified since last run
    DocStore-->>Airflow: file_manifest[]

    Airflow->>SPGraph: GET /sites/{id}/drive/delta<br/>(changed documents since last sync)
    SPGraph-->>Airflow: changed_items[]<br/>{fileId, name, permissions[]}

    Note over Airflow,Parser: Parse phase — extract raw text from each document

    loop for each document (internal + SharePoint)
        Airflow->>Parser: parse(file_bytes, mime_type)
        Parser-->>Airflow: {text, title, author, modified_date}
    end

    Note over Airflow,Chunker: Chunk phase — split text into retrieval units

    loop for each parsed document
        Airflow->>Chunker: chunk(text, strategy="semantic")
        Chunker-->>Airflow: chunks[]
    end

    Note over Airflow,PG: Metadata persistence — record ingested docs before indexing

    Airflow->>PG: INSERT INTO documents<br/>{id, title, source_type, source_path,<br/>permissions_snapshot, ingested_at}
    PG-->>Airflow: document_id

    Note over Airflow,OS: Indexing phase — embed each chunk and write to OpenSearch<br/>Auth metadata stamped on every chunk at this point

    loop for each chunk
        Airflow->>Embedder: embed(chunk.text)
        Embedder-->>Airflow: vector[1024]

        Airflow->>OS: index({<br/>  document_id,<br/>  chunk_text,<br/>  vector,<br/>  source_type: "internal_doc" | "sharepoint",<br/>  auth_metadata: {<br/>    sharepoint_permission_groups[],<br/>    classification_label,<br/>    org_unit_tags[]<br/>  }<br/>})
        OS-->>Airflow: indexed_chunk_id
    end

    Airflow->>PG: UPDATE ingestion_log<br/>SET status="complete", chunk_count=N

    Note over OS: Index now contains chunks from internal docs<br/>and SharePoint, each tagged with auth metadata.<br/>SAP data is NOT pre-indexed — it is queried live.
```

---

## Diagram 2 — Query flow (per user request, all three sources)

This is the runtime flow. A single user query fans out to three sources.
Internal documents and SharePoint use the pre-built OpenSearch index.
SAP data is retrieved live via OData V4 through Integration Suite.
All three paths are gated by the same unified auth envelope resolved at login.

```mermaid
sequenceDiagram
    autonumber

    actor User
    participant UI as Frontend<br/>(Web UI/App)
    participant API as FastAPI<br/>(query router)
    participant AuthRes as Auth resolver<br/>(your contribution)
    participant SAPAuth as SAP Integration Suite<br/>(OData V4 — /UserAuthContext)
    participant GraphAuth as Microsoft Graph API<br/>(user permissions)
    participant QuerySvc as Query service<br/>(your contribution)
    participant OS as OpenSearch<br/>(scoped retrieval)
    participant LLM as Ollama<br/>(local LLM inference)
    participant SAPData as SAP Integration Suite<br/>(OData V4 — entity endpoints)
    participant PG as PostgreSQL<br/>(audit log)

    User->>UI: Submit query<br/>"What is the budget status<br/>for the West Africa project?"
    UI->>API: POST /query<br/>{user_id, query_text, session_token}

    Note over API,AuthRes: Auth resolution phase — runs once per session, cached with TTL

    API->>AuthRes: resolve(user_id, session_token)

    AuthRes->>SAPAuth: GET /UserAuthContext?user={user_id}<br/>(OData V4 via Integration Suite)
    SAPAuth-->>AuthRes: {<br/>  roles[],<br/>  auth_objects: [{object: "F_BKPF_BUK", BUKRS: "1000"}, ...],<br/>  cost_centres[],<br/>  org_units[]<br/>}

    AuthRes->>GraphAuth: GET /v1.0/me/transitiveMemberOf
    GraphAuth-->>AuthRes: {aad_groups[], sharepoint_site_permissions[]}

    AuthRes->>AuthRes: normalise_to_scope_tokens()<br/>Merge SAP field-value constraints +<br/>SharePoint groups into unified envelope

    AuthRes-->>API: scope_tokens {<br/>  sap: {bukrs: "1000", cost_centres: [...]},<br/>  sharepoint: {permitted_groups: [...]},<br/>  classification_floor: "internal"<br/>}

    Note over API,OS: Retrieval phase — documents + SharePoint (pre-indexed in OpenSearch)

    API->>QuerySvc: query(query_text, scope_tokens)
    QuerySvc->>QuerySvc: embed(query_text) → query_vector

    QuerySvc->>OS: hybrid_search({<br/>  vector: query_vector,<br/>  keyword: query_text,<br/>  filter: {<br/>    bool: {<br/>      should: [<br/>        {source_type: "internal_doc"},<br/>        {source_type: "sharepoint",<br/>         sharepoint_permission_groups:<br/>           {in: scope_tokens.sharepoint.permitted_groups}}<br/>      ],<br/>      minimum_should_match: 1<br/>    }<br/>  },<br/>  size: 10<br/>})

    Note over OS: Auth metadata filter applied before<br/>vector ranking. Only permitted chunks<br/>are candidates for retrieval.

    OS-->>QuerySvc: doc_chunks[] (filtered, ranked)

    Note over QuerySvc,SAPData: SAP retrieval phase — live OData query, NOT pre-indexed

    QuerySvc->>LLM: generate_odata_query({<br/>  context_chunks: doc_chunks,<br/>  query_text: query_text,<br/>  system: "Output a single OData V4 $filter expression only.<br/>           Do not explain. Do not add prose."<br/>})
    LLM-->>QuerySvc: $filter=ProjectRegion eq 'West Africa'<br/>and BudgetYear eq 2026

    QuerySvc->>QuerySvc: inject_auth_filter(<br/>  llm_filter,<br/>  scope_tokens.sap<br/>)<br/>Appends: and CompanyCode eq '1000'<br/>and CostCentre in ('CC100','CC101')

    Note over QuerySvc: LLM-generated filter is never<br/>trusted alone. Auth constraints<br/>are always appended programmatically.

    QuerySvc->>SAPData: GET /ProjectFinancials?<br/>$filter={combined_filter}<br/>&$select=ProjectId,Region,Budget,Actual<br/>&$top=20<br/>(via Integration Suite)

    SAPData-->>QuerySvc: sap_records[]

    Note over QuerySvc,LLM: Generation phase — synthesise answer from all retrieved context

    QuerySvc->>LLM: generate_answer({<br/>  query: query_text,<br/>  doc_chunks: doc_chunks,<br/>  sap_records: sap_records,<br/>  system: "Answer using only the provided context.<br/>           Cite source type for each claim."<br/>})
    LLM-->>QuerySvc: answer_text + source_citations[]

    Note over QuerySvc,PG: Audit phase — every query is logged with full trace

    QuerySvc->>PG: INSERT INTO query_audit_log ({<br/>  user_id,<br/>  query_text,<br/>  scope_token_hash,<br/>  odata_filter_used,<br/>  opensearch_filter_used,<br/>  chunks_retrieved,<br/>  sap_records_retrieved,<br/>  answer_hash,<br/>  timestamp<br/>})
    PG-->>QuerySvc: audit_id

    QuerySvc-->>API: {<br/>  answer: answer_text,<br/>  sources: [{type, title, excerpt}],<br/>  audit_id<br/>}
    API-->>UI: JSON response
    UI-->>User: Answer with cited sources<br/>+ source type labels (doc / SAP / SharePoint)
```

---

## Key architectural decisions visible in these diagrams

| Decision                                 | Where it appears           | Why it matters                                                                                                                                                 |
| ---------------------------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SAP data is never pre-indexed            | Diagram 2, retrieval phase | ERP data changes frequently. Pre-indexing creates stale data risk and auth drift. Live OData query is always current.                                          |
| Documents and SharePoint ARE pre-indexed | Diagram 1                  | Unstructured docs change less frequently. Pre-indexing enables fast vector similarity search at query time.                                                    |
| Auth metadata stamped at ingestion       | Diagram 1, indexing loop   | Document permissions are baked into the index. A permission change requires re-ingestion — known limitation to document.                                       |
| LLM filter is never trusted alone        | Diagram 2, SAP retrieval   | The LLM generates a business filter (region, year). Auth constraints (company code, cost centre) are appended programmatically. This is the security boundary. |
| Single auth resolution per session       | Diagram 2, auth phase      | Resolving SAP auth objects and Graph permissions on every query would add unacceptable latency. TTL-cached scope tokens are the practical solution.            |
| Audit log captures scope token hash      | Diagram 2, audit phase     | Full scope token is not stored (PII risk). The hash is sufficient to reconstruct which permissions governed a query if audited.                                |

## What this adds to the arXiv curator baseline

| arXiv curator (baseline)           | Your extension                                           |
| ---------------------------------- | -------------------------------------------------------- |
| Single source: arXiv API           | Three sources: internal docs, SharePoint, SAP            |
| No auth — all users see everything | Unified auth envelope per user per session               |
| Documents only, no structured data | Documents + live structured ERP data                     |
| No OData integration               | SAP Integration Suite OData V4 live queries              |
| No audit trail                     | Full query audit log with scope token hash               |
| Airflow pulls from public API      | Airflow pulls from internal store + SharePoint Graph API |
