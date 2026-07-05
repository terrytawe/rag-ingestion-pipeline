# Auth-Aware Multi-Source RAG — Sequence Diagrams

Four sequence diagrams, one per proposed tech stack.
Each diagram traces a single user query from authentication through
to response, showing every system touched and where authorisation
enforcement occurs.

---

## Stack A — Lean Research Stack
**LlamaIndex + Ollama + Chroma + Custom Python Middleware**

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant App as Application Layer<br/>(FastAPI)
    participant AuthRes as Auth Context Resolver<br/>(Custom Python)
    participant SAPConn as SAP Connector<br/>(pyrfc)
    participant SPConn as SharePoint Connector<br/>(O365 REST Client)
    participant TokenStore as Scope Token Cache<br/>(In-Memory / Redis)
    participant LlamaIdx as RAG Orchestrator<br/>(LlamaIndex)
    participant Chroma as Vector Store<br/>(Chroma + Metadata Filter)
    participant Ollama as LLM Inference<br/>(Ollama / Qwen2.5-Coder)
    participant SAPDB as SAP S/4HANA<br/>(CDS Views)
    participant SPDocs as SharePoint<br/>(Document Library)
    participant AuditLog as Audit Log<br/>(File / SQLite)

    User->>App: POST /query {user_id, query_text}
    App->>AuthRes: resolve_scope(user_id)

    Note over AuthRes,SAPConn: Auth resolution phase — runs once per session
    AuthRes->>SAPConn: get_auth_objects(user_id)
    SAPConn->>SAPDB: RFC_READ_TABLE / SUIM auth objects
    SAPDB-->>SAPConn: {roles[], auth_objects[], org_units[]}
    SAPConn-->>AuthRes: SAP scope descriptor

    AuthRes->>SPConn: get_permission_scopes(user_id)
    SPConn->>SPDocs: GET /me/drives + site permissions
    SPDocs-->>SPConn: {site_ids[], list_ids[], access_level}
    SPConn-->>AuthRes: SharePoint scope descriptor

    AuthRes->>AuthRes: normalise_to_scope_tokens()<br/>merge SAP + SP descriptors into<br/>immutable metadata envelope
    AuthRes->>TokenStore: cache(user_id, scope_tokens, ttl=300s)
    AuthRes-->>App: scope_tokens{}

    Note over App,Chroma: Retrieval phase — scope tokens injected as metadata filter
    App->>LlamaIdx: query(query_text, scope_tokens)
    LlamaIdx->>LlamaIdx: embed(query_text) → query_vector
    LlamaIdx->>Chroma: similarity_search(<br/>vector=query_vector,<br/>where={scope_tokens})
    Note over Chroma: Metadata filter applied BEFORE<br/>candidate ranking.<br/>Only permitted chunks returned.
    Chroma-->>LlamaIdx: filtered_chunks[]

    Note over LlamaIdx,Ollama: Generation phase — LLM generates query, not answer
    LlamaIdx->>Ollama: prompt(filtered_chunks, query_text)<br/>"Generate a CDS/SQL query only"
    Ollama-->>LlamaIdx: generated_query (SQL/CDS string)

    Note over LlamaIdx,SAPDB: Deterministic execution — raw rows never seen by LLM
    LlamaIdx->>SAPConn: execute_scoped_query(generated_query, scope_tokens)
    SAPConn->>SAPDB: Execute CDS view query
    SAPDB-->>SAPConn: result_rows[]
    SAPConn-->>LlamaIdx: result_rows[]

    LlamaIdx->>AuditLog: write_audit_entry(<br/>user_id, query_text,<br/>scope_tokens, generated_query,<br/>timestamp)

    LlamaIdx-->>App: {answer: result_rows, query_used: generated_query}
    App-->>User: JSON response + query trace
```

---

## Stack B — Enterprise-Grade Stack
**Haystack Pipelines + vLLM + Qdrant + SAP OData + Microsoft Graph API**

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant App as Application Layer<br/>(FastAPI)
    participant AuthNode as Auth Resolution Node<br/>(Haystack Custom Component)
    participant OData as SAP OData Service<br/>(Integration Suite / Gateway)
    participant GraphAPI as Microsoft Graph API<br/>(SharePoint Permissions)
    participant Pipeline as Haystack Query Pipeline<br/>(Orchestrator)
    participant ScopeNode as Scope Enforcement Node<br/>(Haystack Component)
    participant Qdrant as Vector Store<br/>(Qdrant + Payload Filter)
    participant Reranker as Reranker Node<br/>(Haystack BGE Reranker)
    participant vLLM as LLM Inference<br/>(vLLM / Qwen2.5-Coder)
    participant SAPDB as SAP S/4HANA<br/>(OData Endpoint)
    participant AuditNode as Audit Node<br/>(Haystack Component)

    User->>App: POST /query {bearer_token, query_text}
    App->>App: validate_bearer_token(bearer_token)
    App->>Pipeline: run(query_text, identity_claims)

    Note over Pipeline,AuthNode: Auth node fires first in pipeline — blocks downstream
    Pipeline->>AuthNode: resolve(identity_claims)
    AuthNode->>OData: GET /UserRoles?$filter=user_id eq '{id}'
    OData->>SAPDB: Evaluate auth objects via OData
    SAPDB-->>OData: roles[], auth_objects[], cost_centres[]
    OData-->>AuthNode: SAP permission payload

    AuthNode->>GraphAPI: GET /me/memberOf + sites/{id}/permissions
    GraphAPI-->>AuthNode: SP groups[], site_access_levels[]

    AuthNode->>AuthNode: build_scope_envelope()<br/>→ immutable ScopeToken dataclass
    AuthNode-->>Pipeline: scope_token passed as pipeline state

    Note over Pipeline,ScopeNode: Scope enforcement node — validates token before retrieval
    Pipeline->>ScopeNode: enforce(scope_token, query_text)
    ScopeNode->>ScopeNode: validate_token_integrity()<br/>check TTL, signature, source flags
    ScopeNode-->>Pipeline: validated_scope_token

    Note over Pipeline,Qdrant: Retrieval node — payload filter built from scope token
    Pipeline->>Qdrant: search(<br/>vector=embed(query_text),<br/>filter={payload: scope_token.qdrant_filter()},<br/>limit=20)
    Note over Qdrant: Payload filter evaluated at index level.<br/>No post-retrieval filtering needed.
    Qdrant-->>Pipeline: candidate_chunks[] (pre-filtered)

    Pipeline->>Reranker: rerank(query_text, candidate_chunks)
    Reranker-->>Pipeline: top_k_chunks[]

    Note over Pipeline,vLLM: Generation node — structured prompt, query output only
    Pipeline->>vLLM: POST /v1/chat/completions<br/>{system: "output SQL only",<br/>context: top_k_chunks,<br/>query: query_text}
    vLLM-->>Pipeline: generated_sql_query

    Note over Pipeline,SAPDB: Execution node — deterministic, scope-bound
    Pipeline->>OData: GET /EntitySet?$filter={scoped_query}
    Note over OData: OData service enforces its own<br/>auth independently — double boundary
    SAPDB-->>OData: result_set[]
    OData-->>Pipeline: result_set[]

    Pipeline->>AuditNode: log(<br/>user_id, scope_token_hash,<br/>query, generated_sql,<br/>chunks_retrieved, timestamp)
    AuditNode-->>Pipeline: audit_id

    Pipeline-->>App: {result: result_set, audit_id, query_trace}
    App-->>User: JSON response
```

---

## Stack C — Hybrid Orchestration Stack
**LlamaIndex (ingestion) + LangGraph (orchestration) + Weaviate + Ollama/vLLM**

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant App as Application Layer<br/>(FastAPI)
    participant Graph as LangGraph Agent<br/>(State Machine)
    participant AuthState as Auth State Node<br/>(LangGraph Node)
    participant GraphAPI as Microsoft Graph API
    participant pyrfc as SAP Connector<br/>(pyrfc)
    participant RetrieveState as Retrieval State Node<br/>(LangGraph Node)
    participant Weaviate as Vector Store<br/>(Weaviate + Multi-tenancy)
    participant GenState as Generation State Node<br/>(LangGraph Node)
    participant LLM as LLM Inference<br/>(Ollama dev / vLLM eval)
    participant ExecState as Execution State Node<br/>(LangGraph Node)
    participant SAPDB as SAP S/4HANA
    participant AuditState as Audit State Node<br/>(LangGraph Node)

    User->>App: POST /query {user_id, query_text}
    App->>Graph: invoke({user_id, query_text})

    Note over Graph: LangGraph initialises typed state object.<br/>All nodes read/write shared state.<br/>Auth token propagates as immutable field.

    Graph->>AuthState: enter node: resolve_auth
    Note over AuthState: First node in graph.<br/>Conditional edge: if resolution fails → END
    AuthState->>pyrfc: call RFC_GET_USEROBJECTS(user_id)
    pyrfc->>SAPDB: RFC call → auth objects
    SAPDB-->>pyrfc: {roles, auth_objects, company_codes}
    pyrfc-->>AuthState: SAP auth descriptor

    AuthState->>GraphAPI: GET /v1.0/me/transitiveMemberOf
    GraphAPI-->>AuthState: AAD groups + SP site permissions

    AuthState->>AuthState: normalise_to_scope_tokens()<br/>→ write immutable scope_tokens to graph state
    Note over AuthState: scope_tokens written to state once.<br/>Cannot be mutated by downstream nodes.
    AuthState-->>Graph: state.scope_tokens = {sap: [...], sp: [...]}

    Graph->>RetrieveState: enter node: scoped_retrieval
    RetrieveState->>RetrieveState: build_weaviate_filter(state.scope_tokens)
    Note over RetrieveState: Filter maps scope tokens to<br/>Weaviate tenant IDs + property filters.<br/>Multi-tenancy = hard data isolation.
    RetrieveState->>Weaviate: nearText query<br/>+ where filter (tenant + permissions)<br/>+ hybrid BM25 + vector
    Note over Weaviate: Multi-tenancy enforces data isolation.<br/>Hybrid search improves recall<br/>on structured SAP field names.
    Weaviate-->>RetrieveState: filtered_chunks[]
    RetrieveState-->>Graph: state.chunks = filtered_chunks[]

    Graph->>GenState: enter node: generate_query
    Note over GenState: LLM sees chunks only.<br/>Prompted to output SQL/CDS — no prose answer.
    GenState->>LLM: prompt(state.chunks, state.query_text)<br/>"Return a single SQL statement"
    LLM-->>GenState: generated_query (SQL string)
    GenState-->>Graph: state.generated_query = sql_string

    Graph->>ExecState: enter node: execute_query
    Note over ExecState: Scope tokens re-validated before execution.<br/>Conditional edge: if token expired → AUTH node
    ExecState->>ExecState: validate_scope_tokens(state.scope_tokens)
    ExecState->>pyrfc: execute_cds_query(<br/>state.generated_query,<br/>state.scope_tokens.sap)
    pyrfc->>SAPDB: Execute scoped CDS view query
    SAPDB-->>pyrfc: result_rows[]
    pyrfc-->>ExecState: result_rows[]
    ExecState-->>Graph: state.result = result_rows[]

    Graph->>AuditState: enter node: write_audit
    AuditState->>AuditState: persist_audit_record(<br/>user_id=state.user_id,<br/>scope_hash=hash(state.scope_tokens),<br/>generated_query=state.generated_query,<br/>chunk_ids=state.chunk_ids,<br/>timestamp=now())
    AuditState-->>Graph: state.audit_id

    Graph-->>App: final state {result, audit_id, query_trace}
    App-->>User: JSON response
```

---

## Stack D — Postgres-Native Stack
**LlamaIndex + SQLAlchemy + pgvector + PostgreSQL RLS + Ollama**

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant App as Application Layer<br/>(FastAPI)
    participant AuthRes as Auth Context Resolver<br/>(Python Service)
    participant pyrfc as SAP Connector<br/>(pyrfc)
    participant SPConn as SharePoint Connector<br/>(O365 REST Client)
    participant PGSession as PostgreSQL Session Manager<br/>(SQLAlchemy)
    participant PG as PostgreSQL 16<br/>(pgvector + RLS)
    participant LlamaIdx as RAG Orchestrator<br/>(LlamaIndex + SQLAlchemy store)
    participant Ollama as LLM Inference<br/>(Ollama / Qwen2.5-Coder)
    participant AuditTbl as Audit Table<br/>(PostgreSQL audit_log)

    Note over PG: RLS policies pre-defined per source.<br/>Policy evaluates current_setting('app.scope_token')<br/>against row-level auth_metadata column.

    User->>App: POST /query {user_id, query_text}
    App->>AuthRes: resolve_scope(user_id)

    AuthRes->>pyrfc: get_auth_objects(user_id)
    pyrfc->>pyrfc: RFC_READ_TABLE → auth objects
    pyrfc-->>AuthRes: {roles[], auth_objects[], cost_centres[]}

    AuthRes->>SPConn: get_permission_scopes(user_id)
    SPConn-->>AuthRes: {site_ids[], list_ids[], access_levels[]}

    AuthRes->>AuthRes: serialise_to_pg_scope_token()<br/>→ JSON string compatible with<br/>PostgreSQL RLS policy evaluation
    AuthRes-->>App: pg_scope_token (JSON)

    Note over App,PGSession: Session setup — scope token injected at connection level
    App->>PGSession: open_session(pg_scope_token)
    PGSession->>PG: SET LOCAL app.scope_token = '{pg_scope_token}'
    Note over PG: All subsequent queries on this session<br/>evaluated against RLS policy.<br/>Token cannot be changed mid-session.
    PG-->>PGSession: session ready

    Note over App,LlamaIdx: Retrieval — pgvector query runs inside RLS session
    App->>LlamaIdx: query(query_text, session)
    LlamaIdx->>LlamaIdx: embed(query_text) → query_vector
    LlamaIdx->>PG: SELECT id, chunk_text, metadata<br/>FROM embeddings<br/>ORDER BY embedding <=> query_vector<br/>LIMIT 20
    Note over PG: RLS policy intercepts query.<br/>Evaluates auth_metadata JSONB column<br/>against app.scope_token setting.<br/>Rows failing policy invisible to query.
    PG-->>LlamaIdx: filtered_chunks[] (RLS enforced)

    Note over LlamaIdx,Ollama: Generation — LLM outputs SQL only
    LlamaIdx->>Ollama: prompt(filtered_chunks, query_text)<br/>"Output a single SQL SELECT statement"
    Ollama-->>LlamaIdx: generated_sql (string)

    Note over LlamaIdx,PG: Execution — same RLS session, scope cannot widen
    LlamaIdx->>PG: EXECUTE generated_sql<br/>(within same RLS session)
    Note over PG: RLS enforced on execution too.<br/>Even if generated SQL attempts<br/>broader SELECT, policy blocks it.
    PG-->>LlamaIdx: result_rows[]

    LlamaIdx->>PG: INSERT INTO audit_log (<br/>user_id, scope_token_hash,<br/>generated_sql, chunk_ids,<br/>row_count, timestamp)<br/>VALUES (...)
    PG-->>LlamaIdx: audit_id

    LlamaIdx-->>App: {result: result_rows, audit_id, sql_used}
    App->>PGSession: close_session()
    PGSession->>PG: RESET app.scope_token
    App-->>User: JSON response
```

---

## Reading guide

| Symbol / pattern | Meaning across all diagrams |
|---|---|
| `Note over X` | Where auth enforcement actually happens — these are the security boundary markers |
| Numbered steps | Correspond to pipeline phases: auth resolution, retrieval, generation, execution, audit |
| `-->>` dashed return arrows | Data flowing back up the call chain |
| `->>` solid arrows | Active calls / requests |
| Conditional edges (Stack C) | LangGraph-specific: graph exits early if auth fails rather than continuing with degraded scope |
| `SET LOCAL app.scope_token` (Stack D) | The PostgreSQL RLS activation step — most architecturally significant line in that diagram |

## Key architectural difference across stacks

| Stack | Where auth is enforced | Enforcement mechanism |
|---|---|---|
| A (Lean) | Application layer + Chroma metadata filter | Python middleware injects filter before vector search |
| B (Enterprise) | Haystack pipeline node + Qdrant payload filter | Auth is a first-class pipeline component, auditable as a node |
| C (LangGraph) | Graph state machine + Weaviate multi-tenancy | Auth token is immutable graph state, tenant isolation is structural |
| D (Postgres) | Database layer — PostgreSQL RLS | Scope token set at session level, policy enforced by DB engine on every query |
