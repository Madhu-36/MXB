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


## 2. Local Embedding Models & Quantization Strategy
Selecting the optimal embedding model requires balancing semantic clustering quality (MTEB benchmark scores) with CPU and integrated GPU execution budgets.

### Model Evaluation Matrix
| Model Identifier | Embedding Dim | Context Window | MTEB Score | Quantized Size | Inference Latency (CPU) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`nomic-embed-text-v1.5`** | 768 / 256 (Matryoshka)| 8,192 tokens | 62.28 | 138 MB (Q8_0) | 18ms / chunk |
| **`bge-small-en-v1.5`** | 384 | 512 tokens | 62.11 | 67 MB (Q8_0) | 9ms / chunk |
| **`all-MiniLM-L6-v2`** | 384 | 256 tokens | 56.26 | 45 MB (INT8) | 6ms / chunk |

### Matryoshka Dimensionality Reduction
MXB adopts `nomic-embed-text-v1.5` with Matryoshka Representation Learning (MRL), allowing 768-dimensional embeddings to be truncated to **256 dimensions** with less than 1.5% loss in retrieval accuracy, reducing memory footprint and cosine vector calculation time by 66%.


## 3. SQLite-Vec In-Process Vector Extension Integration
Rather than maintaining a separate vector database process, MXB integrates **`sqlite-vec`**, a modern, lightweight C-extension for SQLite written specifically for fast vector math and zero external dependencies.

### Virtual Table Schema Definition
```sql
-- Load vector search extension dynamically
SELECT load_extension('sqlite_vec');

-- Create persistent vector virtual table
CREATE VIRTUAL TABLE vec_documents USING vec0(
  chunk_id INTEGER PRIMARY KEY,
  embedding float[256] distance_metric=cosine
);

-- Metadata correlation table
CREATE TABLE document_metadata (
  chunk_id INTEGER PRIMARY KEY,
  file_path TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  checksum TEXT NOT NULL
);
```

### High-Speed Vector Insertion
Vector arrays are encoded as continuous 32-bit float buffers and inserted directly through standard parameterized SQLite `INSERT` statements, enabling atomic transactions across metadata and embeddings.


## 4. Vector Similarity Metrics & Distance Formulations
MXB standardizes on normalized vector metrics to accelerate similarity calculations.

### Mathematical Formulations
1. **Cosine Similarity**:
   $$\text{Cosine}(\mathbf{u}, \mathbf{v}) = \frac{\mathbf{u} \cdot \mathbf{v}}{\|\mathbf{u}\| \|\mathbf{v}\|}$$
   Cosine distance is defined as $1 - \text{Cosine}(\mathbf{u}, \mathbf{v})$.
2. **Normalized Dot Product (Inner Product)**:
   When embedding vectors are L2-normalized upon extraction ($\|\mathbf{u}\| = 1$ and $\|\mathbf{v}\| = 1$), Cosine Similarity simplifies directly to the scalar dot product:
   $$\mathbf{u} \cdot \mathbf{v} = \sum_{i=1}^{d} u_i v_i$$
3. **Squared Euclidean (L2) Distance**:
   $$D_{\text{L2}}^2(\mathbf{u}, \mathbf{v}) = \sum_{i=1}^{d} (u_i - v_i)^2 = 2 - 2(\mathbf{u} \cdot \mathbf{v})$$

By pre-normalizing all chunk vectors upon insertion, MXB evaluates nearest neighbors using vectorized AVX2/AVX-512 SIMD dot-product instructions in under 12 nanoseconds per comparison.


## 5. Hierarchical Navigable Small World (HNSW) Indexing
For collections exceeding 10,000 document chunks, brute-force linear scans ($O(N)$) degrade real-time performance. MXB utilizes an in-process **HNSW graph** indexing structure.

```
Layer 2 (Express):  [Node A] -----------------------------------------> [Node Z]
                         |                                                    |
Layer 1 (Regional): [Node A] -------------> [Node M] -----------------> [Node Z]
                         |                       |                            |
Layer 0 (Dense):    [Node A] -> [Node C] -> [Node M] -> [Node Q] -----> [Node Z]
```

### Index Hyperparameters
- **`M` (Max Links per Node)**: Set to `16`. Controls memory overhead and graph connectivity.
- **`efConstruction`**: Set to `64`. Governs index build quality and edge pruning thoroughness.
- **`efSearch`**: Set to `32`. Governs the size of the dynamic priority queue during nearest-neighbor queries.
- **Search Complexity**: Drops from linear $O(N)$ to logarithmic $O(\log N)$, sustaining <2ms lookups across 100,000 vectors.


## 6. Semantic Document Chunking & Token Windowing
Naive character-length splitting destroys syntactic cohesion and splits code blocks across chunks. MXB employs a **Hierarchical Recursive Chunking** pipeline.

### Chunking Protocol
```python
def chunk_document(text: str, max_tokens: int = 512, overlap_tokens: int = 64) -> list[str]:
    # 1. Split hierarchically on major markdown boundaries
    separators = ["\n## ", "\n### ", "\n\n", "\n", " "]
    chunks = []
    
    # Recursive boundary splitting preserves header context
    # Overlap buffer retains context across neighboring windows
    return chunks
```

### Semantic Header Injection
When a chunk is generated from a nested section, MXB automatically prepends document breadcrumbs:
`[Document: architecture.md > Section: Vector Database > Subsection: HNSW Indexing]`
This contextual prefix ensures that isolated chunks retain semantic anchors during vector embedding.


## 7. Multi-Format Document Ingestion Pipelines
MXB includes dedicated, format-aware extraction adapters designed for desktop data sources.

### Ingestion Adapters
- **Markdown / Obsidian**: Preserves frontmatter YAML metadata, resolves `[[wikilinks]]`, strips raw HTML tags, and maintains code fence blocks intact.
- **PDF Documents**: Employs `pypdf` with native layout analysis, extracting running headers, body text, tables, and footnote references.
- **Source Code Repositories**: Uses AST parsing (Abstract Syntax Tree) to extract complete function definitions, class structures, and docstrings rather than arbitrary line breaks.
- **Plain Text & Transcripts**: Segments timestamped audio transcripts into 60-second conversational turns.


## 8. Metadata Schema & Document Lineage Tracking
To support filtered retrieval (e.g. *"Only search files modified this week in my Obsidian vault"*), vector chunks are linked to structured metadata.

### SQLite Relational Schema
```sql
CREATE TABLE document_nodes (
    id TEXT PRIMARY KEY,
    source_uri TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size_bytes INTEGER,
    modified_timestamp INTEGER,
    sha256_hash TEXT NOT NULL
);

CREATE TABLE chunk_nodes (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT REFERENCES document_nodes(id) ON DELETE CASCADE,
    chunk_index INTEGER,
    token_count INTEGER,
    content TEXT NOT NULL,
    header_path TEXT
);

CREATE INDEX idx_chunks_doc_id ON chunk_nodes(doc_id);
CREATE INDEX idx_docs_modified ON document_nodes(modified_timestamp);
```


## 9. Hybrid Search: Dense Vector & Sparse BM25 Fusion
Dense vector retrieval excels at conceptual semantic similarity but frequently struggles with exact alphanumeric identifiers (e.g., error codes `0x80070005`, function names `calculate_rms`, or ticket IDs `MXB-104`). MXB fuses dense semantic vectors with **SQLite FTS5** sparse BM25 text search.

```
User Query: "find error 0x80070005 in audio pipeline"
       |
       +---> [ Dense Vector Search (sqlite-vec) ] ------> Rank List A (Conceptual matches)
       |
       +---> [ Sparse BM25 Search (SQLite FTS5) ] ------> Rank List B (Exact keyword matches)
       |
       v
  [ Reciprocal Rank Fusion (RRF) ] --------------------> Final Ranked Top-K Documents
```

### SQLite FTS5 Full-Text Table
```sql
CREATE VIRTUAL TABLE fts_documents USING fts5(
  content,
  header_path,
  tokenize='porter unicode61'
);
```


## 10. Reciprocal Rank Fusion (RRF) Re-ranking Algorithm
To combine disparate scoring spaces (cosine distance in $[0, 2]$ vs BM25 unbounded positive scores), MXB utilizes parameter-free **Reciprocal Rank Fusion (RRF)**.

### Mathematical Formulation
$$\text{RRF\_Score}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
Where:
- $M$: Set of ranking systems ($\{\text{Dense Vector}, \text{Sparse BM25}\}$).
- $r_m(d)$: Rank position of document $d$ in system $m$ (1-indexed).
- $k$: Smoothing constant, set to $60$ (standardized to prevent top ranks from dominating).

### Implementation
```python
def reciprocal_rank_fusion(dense_ranks: list[int], sparse_ranks: list[int], k: int = 60) -> list[tuple[int, float]]:
    scores = {}
    for rank, doc_id in enumerate(dense_ranks, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank))
    for rank, doc_id in enumerate(sparse_ranks, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```


## 11. Cross-Encoder Re-Ranking Pipeline (`bge-reranker-base`)
While bi-encoders produce vectors independently for query and document, a **Cross-Encoder** jointly processes the query and passage through self-attention layers, computing precise relevance scores.

### Two-Stage Retrieval Pipeline
1. **Stage 1 (High Recall Retrieval)**: Hybrid Search retrieves top-25 candidate passages in ~12ms.
2. **Stage 2 (High Precision Cross-Encoder)**: `bge-reranker-base` scores all 25 candidates, re-ordering them and filtering out irrelevant passages below a relevance threshold of $0.45$.

```python
# Cross-encoder joint evaluation: [CLS] Query [SEP] Passage [SEP]
relevance_score = cross_encoder.predict([(query, passage_content)])
```
Stage 2 selects the top-3 to top-5 most relevant passages for LLM prompt injection.


## 12. Contextual Compression & Redundant Token Pruning
Injecting raw 512-token chunks often floods the LLM context window with irrelevant boilerplate text. MXB applies **Contextual Sentence Extraction**.

### Compression Strategy
1. **Sentence Boundary Parsing**: Splits candidate chunk into individual sentences.
2. **Relevance Filtering**: Retains only sentences whose semantic similarity or keyword overlap with the user query exceeds threshold $\theta = 0.55$.
3. **Token Conservation**: Reduces prompt injection size by **45–60%**, preserving LLM generation speed on CPU.


## 13. Dynamic Context Budget Management
MXB dynamically partitions its prompt context budget based on the active LLM backend and available hardware memory.

### Context Budget Allocation Matrix
| Model Backend | Total Context | System Prompt | User History | RAG Retrieval Budget | Generation Reserve |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Local Ollama (CPU)** | 2,048 tokens | 300 tokens | 250 tokens | **1,100 tokens (~3 chunks)**| 398 tokens |
| **Local Ollama (dGPU)**| 4,096 tokens | 450 tokens | 600 tokens | **2,400 tokens (~6 chunks)**| 646 tokens |
| **NVIDIA Cloud NIM**   | 8,192 tokens | 500 tokens | 1,200 tokens| **5,000 tokens (~12 chunks)**| 1,492 tokens |

If retrieved chunks exceed the designated budget, lowest-scoring passages from Stage 2 re-ranking are systematically dropped.


## 14. Real-Time Incremental Indexing via File Watchers
To ensure MXB's second brain reflects the user's latest work, an asynchronous background file watcher tracks modifications across registered document directories.

### Watcher Implementation
```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class DocumentWatcher(FileSystemEventHandler):
    def __init__(self, indexer):
        self.indexer = indexer

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith((".md", ".txt", ".py")):
            self.indexer.queue_reindex(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.indexer.delete_document(event.src_path)
```
Changes are debounced by 2.0 seconds to prevent thrashing during active editing sessions.


## 15. Semantic Clipboard History Vectorization
MXB maintains an ephemeral vector index of recent clipboard text entries, enabling conversational queries over recently copied information.

### Workflow
1. **Clipboard Hook**: `pyperclip` periodically polls clipboard text changes with SHA-256 deduplication.
2. **Instant Vectorization**: Captured text is embedded into a dedicated SQLite table `clipboard_vectors` (retained for 48 hours).
3. **Conversational Recall**: When user says: *"What was that API URL I copied earlier?"*, MXB performs vector similarity over recent clipboard entries and speaks the answer.


## 16. Temporal Recency Decay & Desktop Context Binding
Retrieval relevance is heavily influenced by the user's immediate workflow. A document opened in the active window right now is significantly more relevant than a document modified three months ago.

### Time-Decay Scoring Multiplier
$$\text{DecayFactor}(t) = \exp\left(-\lambda \cdot \Delta t\right)$$
Where:
- $\Delta t$: Elapsed time in days since last document access.
- $\lambda$: Half-life decay constant ($\lambda = 0.05$).

### Active Window Boosting
Passages originating from the file or application currently focused in `pygetwindow` receive an automatic **+25% relevance boost**, prioritizing immediate context.


## 17. Security & Encryption at Rest via SQLCipher
Personal knowledge bases contain sensitive notes, proprietary code, and personal communications. MXB secures its local database using **SQLCipher AES-256**.

### Encryption Architecture
```python
import sqlite3

def open_secure_database(db_path: str, master_key: str):
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA key = '{master_key}';")
    conn.execute("PRAGMA cipher_compatibility = 4;")
    conn.execute("PRAGMA kdf_iter = 64000;")
    return conn
```
- **Key Derivation**: PBKDF2 with 64,000 SHA-512 iterations.
- **Page Encryption**: Every 4096-byte SQLite database page is individually encrypted with CBC mode AES-256 and HMAC verification.


## 18. Zero-Copy Embedding Batching via DirectML
To avoid saturating the host CPU during bulk document ingestion, MXB offloads ONNX embedding extraction to the integrated GPU (Intel UHD Graphics) via DirectML.

### DirectML Tensor Pipeline
- **Execution Provider**: `DmlExecutionProvider` in ONNX Runtime.
- **Dynamic Batching**: Groups pending document chunks into batches of 16 vectors.
- **Compute Offload**: Leaves CPU P-cores free for voice pipeline VAD and responsive PySide6 UI rendering.


## 19. Prompt Synthesis & Citation Grounding Templates
Retrieved context is injected into the LLM system prompt using structured, citation-grounded formatting.

### Grounding Prompt Structure
```
You are MXB, acting as the user's Second Brain.
Answer the user's question using ONLY the provided verified context passages below.
For every factual statement you make, cite the corresponding source in brackets (e.g. [Doc 1]).

--- VERIFIED LOCAL CONTEXT ---
[Doc 1] Source: "C:/Vault/ProjectAlpha.md" (Modified: Yesterday)
Content: Project Alpha release milestone is scheduled for December 15, 2026.

[Doc 2] Source: "C:/Vault/TeamNotes.md" (Modified: 3 days ago)
Content: Lead architect for Project Alpha is Sarah Connor.
------------------------------

User Question: "When is Project Alpha releasing and who leads it?"
```


## 20. Hallucination Mitigation & Attribution Verifier
To prevent LLM confabulation, MXB implements a post-generation **Attribution Verifier**.

### Verification Algorithm
1. **Entity Extraction**: Extracts proper nouns, numerical quantities, and dates from the LLM reply.
2. **Passage Cross-Check**: Confirms that every extracted entity exists verbatim within the retrieved context passages.
3. **Confidence Scoring**: If an entity in the reply is unsupported by the context, MXB prefixes the speech output with:
   *"Based on your notes, [answer], but please verify since this was not explicitly confirmed."*


## 21. Offline Web Knowledge Caching & Semantic Search
When MXB performs online web searches via DuckDuckGo, retrieved articles and documentation pages are automatically ingested into an offline semantic cache.

### Offline Knowledge Vault
- **Cache Format**: Clean markdown extracts stored in `~/.mxb/web_cache/`.
- **Automatic TTL**: Retains cached documentation for 30 days.
- **Offline Querying**: When internet connectivity drops, queries are automatically routed to the offline web cache, enabling answers without active network access.


## 22. Cognitive Memory Consolidation & Forgetting Curves
Human memory consolidates daily experiences into higher-level abstractions while pruning trivial noise. MXB implements a **Nightly Memory Consolidation Daemon**.

### Consolidation Workflow
1. **Cluster Detection**: Identifies related memory bank facts and daily clipboard snippets using DBSCAN vector clustering.
2. **Recursive Summarization**: Synthesizes clusters into concise generalized summaries (e.g. 10 notes about meeting agendas become 1 unified weekly summary).
3. **Ebbinghaus Forgetting Decay**: Decrements importance scores of unreferenced transient facts, archiving dead entries after 90 days.


