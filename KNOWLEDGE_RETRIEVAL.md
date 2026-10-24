# MXB V2.0 - Local RAG & Semantic Knowledge Retrieval Architecture

## 1. Executive Summary & Core Principles
MXB V2.0 includes a production-grade, air-gapped **Retrieval-Augmented Generation (RAG)** engine designed to ground desktop assistant answers in the user's personal documents, code repositories, and local system notes without sending data to external APIs.

```
+-----------------------------------------------------------------------------+
|                     MXB Local Hybrid Retrieval Engine                       |
|                                                                             |
| User Query --> [ Query Normalizer / HyDE ]                                  |
|                      |                                                      |
|         +------------+------------+                                         |
|         |                         |                                         |
|         v                         v                                         |
|  [ BM25 Lexical Search ]   [ Dense Vector Index (HNSW) ]                    |
|  (Inverted Index / Okapi)  (all-MiniLM-L6-v2 ONNX)                          |
|         |                         |                                         |
|         +------------+------------+                                         |
|                      |                                                      |
|                      v                                                      |
|         [ Reciprocal Rank Fusion (RRF) ]                                    |
|                      |                                                      |
|                      v                                                      |
|         [ Cross-Encoder Re-ranker (BGE) ]                                   |
|                      |                                                      |
|                      v                                                      |
|         [ Context Packing & Prompt Assembly ] --> (Llama 3.1 8B LLM)        |
+-----------------------------------------------------------------------------+
```

### Core Architecture Pillars
- **Zero-Cloud Privacy**: Vectorization and ranking execute 100% locally via ONNX Runtime and SIMD C++ extensions.
- **Hybrid Search Precision**: Combines dense semantic similarity with sparse keyword matching (BM25) to prevent hallucinations on technical terminology and exact symbol names.
- **Sub-50ms Retrieval**: HNSW indexing delivers sub-50ms candidate retrieval over 500,000 document chunks.


