# Proof of Concept (POC): RAG Admin Panel Functional Specification

This document outlines the core functional modules and specific requirements needed to build a minimal viable Proof of Concept (POC) for a Retrieval-Augmented Generation (RAG) admin panel.

---

## 1. Knowledge Base Management

This module handles data source ingestion, processing, and scheduling.

### Functional Requirements
*   **Manual File Upload:** Support drag-and-drop for `.pdf`, `.txt`, `.docx`, and `.md` files.
*   **Web Scraping / URL Sync:** Input field to ingest text content from a public website URL.
*   **Chunking Strategy Selector:**
    *   Dropdown to select chunking method (Fixed-size vs. Semantic).
    *   Sliders to adjust **Chunk Size** (e.g., 500 tokens) and **Chunk Overlap** (e.g., 50 tokens).
*   **Document Status Table:** A grid view showing document name, file size, upload date, data source type, and parsing status (*Processing, Success, Failed*).

---

## 2. Vector Database & Search Settings

This module configures how text is converted into numbers (embeddings) and how those numbers are searched.

### Functional Requirements
*   **Embedding Model Selector:** Radio buttons or dropdown to switch between providers (e.g., OpenAI `text-embedding-3-small` vs. Hugging Face local models).
*   **Search Strategy Toggle:** Switch between three retrieval types:
    *   *Semantic Search* (Vector/Dense distance).
    *   *Keyword Search* (BM25/Sparse matching).
    *   *Hybrid Search* (Combines both using Reciprocal Rank Fusion).
*   **Vector DB Connection Status:** Visual indicator showing connection state (Connected/Disconnected) to the database (e.g., Pinecone, Chroma, Qdrant) along with current total vector count.

---

## 3. Retrieval Parameters

This module controls the rules for picking the best text snippets to feed the LLM.

### Functional Requirements
*   **Top-K Slider:** Numerical input/slider to set the maximum number of text chunks retrieved per user query (typically range 1–20).
*   **Score Threshold Slider:** Confidence score cut-off (0.0 to 1.0) to filter out weak or irrelevant search results.
*   **Reranker Toggle:** On/Off switch to enable a secondary reranking step (e.g., Cohere Rerank) to improve result ordering before generation.

---

## 4. Prompt & Model Tuning

This module defines which language model answers user questions and how it behaves.

### Functional Requirements
*   **LLM Provider Selector:** Selection tool for the foundational model (e.g., GPT-4o, Claude 3.5 Sonnet, Llama 3).
*   **Hyperparameter Sliders:**
    *   *Temperature* (0.0 for strict/factual to 1.0 for creative).
    *   *Max Tokens* (Limits the length of the AI response).
*   **System Prompt Editor:** A rich text area pre-populated with a default RAG template, allowing admins to inject instructions (e.g., *"Answer the question using only the provided context. If you do not know, say 'I cannot find that in the documents'."*).

---

## 5. Security & Access Control

This module restricts who can see what data within the system.

### Functional Requirements
*   **Role-Based Access Control (RBAC):** Simple toggle matrix assigning users to three baseline roles: *Super Admin, Content Manager, End User*.
*   **Document Tagging / Metadata Filtering:** Ability to attach "tags" or "clearance levels" to uploaded documents (e.g., `Confidential`, `Public`, `HR-Only`).
*   **User Permission Table:** A searchable list of user accounts with dropdowns to change their access permissions.

---

## 6. Observability & Analytics

This module tracks system performance, user happiness, and cloud infrastructure costs.

### Functional Requirements
*   **Real-time Query Log:** A live feed displaying incoming user questions, retrieved document chunks, final LLM answers, and total execution latency (in milliseconds).
*   **Feedback Counter:** KPI cards summarizing user feedback metrics (Total Thumbs Up count vs. Total Thumbs Down count).
*   **Cost & Token Tracker:** A simple line chart plotting total daily token consumption and estimated API costs over time.
