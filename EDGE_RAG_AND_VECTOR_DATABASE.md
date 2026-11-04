# MXB V2.0 - Edge Vector Database & Local RAG Architecture Guide

## 1. Executive Summary & Knowledge Retrieval Vision
MXB V2.0 elevates desktop intelligence by transforming disparate local files, personal notes, clipboard snippets, and application states into a unified, privacy-first **Local Retrieval-Augmented Generation (Local RAG)** ecosystem. Rather than relying on cloud vector databases (e.g., Pinecone, Weaviate) that expose private personal data to network egress, MXB runs an in-process, high-performance edge vector engine powered by **`sqlite-vec`** and local quantized embedding models.

```
+---------------------------------------------------------------------------------------+
|                       MXB Edge Vector Engine & Local RAG Pipeline                     |
|                                                                                       |
|  [ Obsidian Vaults / Markdown / PDFs / Clipboard / Code ]                             |
|                           |                                                           |
|                           v                                                           |
|  [ Recursive Semantic Chunking (512 Tokens, 64 Overlap) ]                             |
|                           |                                                           |
|                           v                                                           |
|  [ Local Embedding Model: nomic-embed-text-v1.5 INT8 (768 Dim) via ONNX / DirectML ]   |
|                           |                                                           |
|                           v                                                           |
|  +---------------------------------------------------------------------------------+  |
|  |                     In-Process SQLite Vector Store (`sqlite-vec`)               |  |
|  |  - Table: `mxb_embeddings` (HNSW Cosine Distance Index)                         |  |
|  |  - Table: `mxb_fts5_index` (Sparse BM25 Inverted Index)                        |  |
|  |  - AES-256 SQLCipher Encryption at Rest (PRAGMA key)                            |  |
|  +---------------------------------------------------------------------------------+  |
|                           |                                                           |
|                           v                                                           |
|  [ Hybrid Query: Dense Vector Cosine + Sparse BM25 Keyword Search ]                   |
|                           |                                                           |
|                           v                                                           |
|  [ Reciprocal Rank Fusion (RRF, k=60) Multi-List Re-ranking ]                         |
|                           |                                                           |
|                           v                                                           |
|  [ Local Cross-Encoder Re-ranker: bge-reranker-base (Top-5 Selection) ]               |
|                           |                                                           |
|                           v                                                           |
|  [ Dynamic Context Synthesis & Citation Grounding -> LLM Cognitive Brain ]           |
+---------------------------------------------------------------------------------------+
```

### Core Architecture Objectives
- **Zero Cloud Egress**: 100% of embeddings, vector searches, and re-ranking execute locally on device.
- **Sub-15ms Hybrid Retrieval**: Vector distance queries and BM25 lookups complete in under 15ms over 100,000 document chunks.
- **Embedded In-Process Engine**: Zero external database daemons or Docker dependencies; uses native SQLite C-extension bindings.


