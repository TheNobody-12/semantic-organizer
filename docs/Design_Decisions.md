# Semantic Organizer: Master Strategic Vision & Architecture

> **Guiding Principle**: *"Let the AI produce evidence and proposals; let deterministic code and user approval control filesystem changes."*

This document serves as the master architectural specification and phased roadmap for evolving Semantic Organizer from a local file router into a trusted, searchable, and human-governed Personal Knowledge Graph.

---

## 🏛️ Core Architectural Foundations

### 1. Hierarchy of Authority (Source of Truth)
To prevent drift across filesystems, graph databases, and user note vaults, the system enforces a strict source-of-truth hierarchy:

```text
1. taxonomy.yaml               → Defines valid categories, document types, and routing rules
2. Content Hash (SHA-256)      → Immutable document identity
3. Sidecar Metadata (.json/.md)→ Persistent, portable record of last verified classification
4. Neo4j Knowledge Graph       → Queryable indices, entity relations, and chunk provenance
5. Folder Location on Disk     → Derived destination, NOT the semantic source of truth
```

### 2. Proposal-First Restructuring & Data Safety
No autonomous or destructive disk operations are permitted. Any taxonomy evolution or restructuring is strictly proposal-based:

```bash
semantic-organizer restructure --analyze    # Cluster graph & generate taxonomy diff
semantic-organizer restructure --preview    # Produce file-move plan & link impact report
semantic-organizer restructure --apply -i   # Interactively execute with rollback manifest
```

Every restructuring event produces:
- **Taxonomy Diff**: Visual summary of modified categories / document types.
- **File Move Plan**: Exact before/after paths.
- **Rollback Manifest**: Reversible script/journal to undo all moves and graph updates instantly.
- **Obsidian Link Impact Report**: Analysis of affected Markdown backlinks.

### 3. Template-Constrained GraphRAG
Rather than relying on unreliable zero-shot Natural Language to Cypher generation on local LLMs, GraphRAG uses a constrained, template-driven retrieval pipeline:

```text
User Question
    ↓
Entity & Intent Extraction (LLM + schema constraint)
    ↓
Entity Resolution against Neo4j (Fuzzy/Exact Match)
    ↓
Parameterized Cypher Query Templates:
  - Document Mentions Entity [X]
  - Entity [X] co-occurring with Entity [Y]
  - Evidence Chunks for Topic [T] in Category [C]
    ↓
Chunk Retrieval & Context Assembly
    ↓
Grounded Synthesis with Strict Chunk Citations
```

### 4. Non-Intrusive Obsidian Integration
- **Namespaced Metadata**: Injected frontmatter uses a dedicated `semantic:` namespace so existing user YAML keys are never overwritten.
- **Companion Notes by Default**: Binary files (PDF, DOCX) receive clean companion markdown files (`file.pdf.semantic.md`).
- **Opt-In Direct Injection**: Direct frontmatter injection into user `.md` files is explicitly opt-in (`--obsidian-frontmatter`).

---

## 🚦 Phased Implementation Roadmap & Quality Gates

```
Phase 0: Safety & Correctness
   ↓
Phase 1: Reliable Semantic Pipeline (Current)
   ↓
Phase 2: Knowledge Graph Foundation
   ↓
Phase 3: Non-Intrusive Obsidian Vault Integration
   ↓
Phase 4: Constrained Mini GraphRAG
   ↓
Phase 5: Human-Approved Restructuring
   ↓
Phase 6: Optional Autonomous Operations
```

---

### Phase 0: Safety and Correctness (Foundations)
- [x] **Copy-by-default filesystem behavior**: Never delete or move source files implicitly.
- [x] **Dry-run mode (`--dry-run`)**: Full simulation with no disk or graph mutations.
- [x] **Taxonomy validation**: Strict Pydantic models for `taxonomy.yaml` with category and document type enums.
- [x] **Sidecar artifacts**: `.semantic.json` and `.semantic.md` generated alongside outputs.
- [ ] **Path traversal protection & collision handling**: Robust sanitization of destination paths.
- [ ] **Rollback manifest**: Machine-readable undo log generated for every execution.
- [ ] **Baseline evaluation corpus**: Standard test set with expected classifications.

---

### Phase 1: Reliable Semantic Pipeline (Complete)
- [x] **Model verification & prompt**: Verify LM Studio model availability before starting batch runs; prompt interactively if missing.
- [x] **Two-level hierarchical routing**: Route documents to `Category/DocumentType/` based on domain and document purpose.
- [x] **Local SQLite Caching**: Multi-tier cache keyed by `content_hash` (for parsed markdown) and `content_hash + taxonomy_hash + model + prompt_version` (for LLM analyses).
- [x] **Operation Journal (Idempotent Crash Recovery)**: Transactional state machine tracking per document (`planned` → `parsed` → `analyzed` → `graph_written` → `copied` → `verified` → `completed`).
- [x] **Hierarchical Chunking (IBM Docling)**: Replace 8000-char truncation with structure-aware heading/section map-reduce analysis for 50+ page documents.
- [x] **Deterministic Category Aggregation**: Python-weighted chunk scoring with configurable confidence margins.
- [x] **Independent Concurrency Pools**: Dedicated worker limits for CPU parsing vs LLM inference vs Neo4j writes with backpressure.

> **Phase 1 Quality Gate**:
> - Schema valid JSON rate: **≥ 98%**
> - Single-pass classification accuracy: **≥ 90%** on benchmark corpus
> - Long-document (50+ pages) classification accuracy: **≥ 85%**

---

### Phase 2: Knowledge Graph Foundation
- [x] **Core Graph Schema**: `Document`, `Category`, `DocumentType`, `Entity`, `Tag`.
- [x] **Chunk & Section Nodes**: Add `(:Document)-[:HAS_CHUNK]->(:Chunk)-[:PART_OF_SECTION]->(:Section)` for complete explainability.
- [x] **Exact & Near Deduplication**: Detect identical hashes (`:DUPLICATE_OF`) and near-duplicates via similarity without deleting files on disk. (Exact completed; near-dedupe deferred to Phase 3 Vector Embeddings)
- [x] **Graph Rebuild & Reconciliation**: `rebuild-graph` and `reconcile` commands to sync filesystem, sidecars, and Neo4j.
- [x] **Reclassification Workflow**: `reclassify` command re-evaluating specific documents against updated taxonomies using cached parser output.

> **Phase 2 Quality Gate**:
> - Graph reconciliation consistency: **100%** match between sidecars and Neo4j
> - Exact duplicate detection precision: **100%**

---

### Phase 3: Obsidian Vault Integration
- [ ] **Companion Notes**: Auto-generate `.semantic.md` companion notes with backlinks to binary assets.
- [ ] **Namespaced YAML Frontmatter**: Support `semantic:` namespaced frontmatter for native Dataview queries.
- [ ] **Opt-in WikiLinks**: Configurable `[[WikiLink]]` generation for entities and tags without polluting user notes.
- [ ] **Related Document Views**: Generate dynamic "Related Notes" markdown blocks using graph co-occurrence.

---

### Phase 4: Constrained Mini GraphRAG
- [ ] **Interactive Query Shell**: `semantic-organizer query` REPL built with `prompt_toolkit`.
- [ ] **Template-Based Retrieval**: Safe, parameterized Cypher templates for entity/topic queries.
- [ ] **Evidence Assembly & Synthesis**: Feed retrieved chunk text into local LLM for answers.
- [ ] **Mandatory Citations**: Require answers to cite explicit chunk IDs and source page numbers.

> **Phase 4 Quality Gate**:
> - Grounding & citation rate: **100%** of factual claims cite retrieved chunk IDs
> - Zero invalid/malformed Cypher executions

---

### Phase 5: Human-Approved Restructuring
- [ ] **Graph Clustering & Overlap Analysis**: Detect sparse, bloated, or overlapping category distributions.
- [ ] **Taxonomy Recommendation Engine**: Generate formal `taxonomy.diff` suggestions.
- [ ] **Restructure Preview & Plan**: Full dry-run report showing proposed file moves and Obsidian link impacts.
- [ ] **Interactive Execution & Instant Rollback**: User-approved execution with atomic journal and 1-click rollback command (`semantic-organizer undo`).

> **Phase 5 Quality Gate**:
> - Rollback and dry-run success rate: **100%** across test suites
> - Zero unprompted or unconfirmed filesystem relocations

---

### Phase 6: Optional Autonomous Operations (Future / Advanced)
- [ ] **Scheduled Background Reanalysis**: Continuous monitoring of incoming documents.
- [ ] **Policy-Guarded Minor Adjustments**: Automated sub-folder routing for high-confidence (≥ 98%) items only.
- [ ] **Strict Safety Bounds**: Hard limits on batch moves and automatic alerts when confidence drifts.
