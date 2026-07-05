# Retrieval Pipeline: Pre-Filtering & Authorization Propagation

This sequence details how a user's search query triggers a real-time authorization check against SAP, applies pre-filtering before hitting ChromaDB, and returns authorized context to Ollama.

```mermaid
sequenceDiagram
    autonumber
    actor User as End User (Search UI)
    participant MW as RAG Middleware (Python)
    participant SAP as SAP S/4HANA (OData Service)
    participant Map as Auth Mapping Engine
    participant Embed as Embedding Model (Ollama)
    participant VDB as Vector DB (ChromaDB)
    participant LLM as Generator (Ollama LLM)

    User->>MW: Submit Query (Text) + User Session Token
    activate MW

    MW->>SAP: HTTP GET /sap/opu/odata/.../GetUserAuthorizations (User Session)
    activate SAP
    Note over SAP: Evaluates PFCG Roles & Auth Objects<br/>(e.g., Activity 03 for User)
    SAP-->>MW: Return User's Active SAP Authorization Profile
    deactivate SAP

    MW->>Map: Pass User Auth Profile
    activate Map
    Note over Map: Resolves profile to active<br/>Scope Tokens user has access to
    Map-->>MW: Return User Scope Tokens (e.g., ["GRP_FI_2026"])
    deactivate Map

    MW->>Embed: Generate Query Vector (Ollama)
    activate Embed
    Embed-->>MW: Return Query Vector
    deactivate Embed

    MW->>MW: Construct ChromaDB Pre-Filter<br/>where={"auth_tags": {"$in": ["GRP_FI_2026"]}}

    MW->>VDB: collection.query(query_embeddings=vector, where=filter_dict)
    activate VDB
    Note over VDB: Vector DB isolates chunks matching<br/>tags BEFORE computing cosine distance
    VDB-->>MW: Return Authorized Context Chunks
    deactivate VDB

    MW->>MW: Synthesize System Prompt<br/>(Query + Authorized Context Only)

    MW->>LLM: Generate Response (Prompt)
    activate LLM
    LLM-->>MW: Return Natural Language Answer
    deactivate LLM

    MW-->>User: Return Answer (Completely Redacted of Unauthorized Data)
    deactivate MW
```
