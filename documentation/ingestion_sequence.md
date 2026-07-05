# Ingestion Pipeline: Token-Based Document Tagging

This sequence details how documents are ingested via the UI, mapped against SAP authorization rules, tagged with scope tokens, and embedded into ChromaDB.

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Admin / UI Upload
    participant MW as RAG Middleware (Python)
    participant SAP as SAP S/4HANA (OData Service)
    participant Map as Auth Mapping Engine
    participant Embed as Embedding Model (Ollama)
    participant VDB as Vector DB (ChromaDB)

    Admin->>MW: Upload Document + Metadata (Context/Module)
    activate MW
    
    MW->>SAP: HTTP GET /sap/opu/odata/.../GetAuthMetadata (Module Context)
    activate SAP
    SAP-->>MW: Return SAP Auth Objects & Authorization Rules
    deactivate SAP

    MW->>Map: Pass Metadata & SAP Auth Rules
    activate Map
    Note over Map: Translates SAP rules into<br/>generalized scope tokens<br/>(e.g., "GRP_FI_2026")
    Map-->>MW: Return Standardized Scope Tokens (Tags)
    deactivate Map

    MW->>MW: Chunk Document Text
    
    loop For Each Chunk
        MW->>Embed: Generate Vector Embedding (Ollama)
        activate Embed
        Embed-->>MW: Return Embedding Vector
        deactivate Embed
        
        MW->>MW: Construct Metadata Payload<br/>{ "source": doc_id, "auth_tags": ["GRP_FI_2026"] }
        
        MW->>VDB: collection.add(embeddings=vector, documents=text, metadatas=payload)
        activate VDB
        VDB-->>MW: Acknowledge Storage
        deactivate VDB
    end

    MW-->>Admin: Upload & Tagging Successful
    deactivate MW