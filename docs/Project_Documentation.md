## 1. Project Overview

Semantic Organizer is a **local, privacy‑first document intelligence tool** that ingests unstructured files (PDFs, Office docs, text, Markdown), converts them to structured Markdown via IBM Docling, extracts semantic metadata using a local LLM served by LM Studio, and writes everything into a Neo4j knowledge graph for search, routing, and organization. [docling](https://docling.org/)

Primary capabilities:

- 100% local processing: Docling, LM Studio, and Neo4j all run on your machine.  
- Intelligent parsing: Docling converts complex documents into Markdown optimized for semantic analysis. [research.ibm](https://research.ibm.com/publications/docling-an-efficient-open-source-toolkit-for-ai-driven-document-conversion)
- Semantic extraction: LM Studio’s local server exposes an OpenAI‑compatible API; the tool calls a small instruction‑tuned model to produce structured JSON (category, summary, entities). [lmstudio](https://lmstudio.ai/llms-full.txt)
- Knowledge graph: Neo4j stores documents, categories, entities, and relationships for rich semantic queries and future features like project views and Q&A. [development.neo4j](https://development.neo4j.dev/developer/docker/)
- Optional Obsidian integration: Semantic Organizer can treat an Obsidian vault as source/target and pair with a Neo4j graph plugin for visualization. [docs.obsidian](https://docs.obsidian.md/Plugins/Vault)

***

## 2. High‑Level Architecture

### Components

- **CLI Application (Python + Typer)**  
  Entrypoint: `organize-docs <SOURCE_DIRECTORY> <TARGET_DIRECTORY>`  
  - Orchestrates ingestion, parsing, LLM calls, graph writes, and file relocation.

- **Docling Parser Module**  
  - Uses `docling.document_converter.DocumentConverter` with PDF options tuned for speed and PyPdfium2 backend. [docling-project.github](https://docling-project.github.io/docling/reference/document_converter/)
  - Outputs Markdown text plus minimal metadata (pages, headings).

- **LM Studio Integration Module**  
  - Uses OpenAI‑compatible API: `base_url="http://localhost:1234/v1"` with a local instruction model (e.g. Gemma‑2 2B). [lmstudio](https://lmstudio.ai/llms-full.txt)
  - Returns strict JSON matching a schema: `{category, summary, entities, tags, confidence}`.

- **Neo4j Graph Module**  
  - Connects via Bolt on `bolt://localhost:7687` using the official Python driver.  
  - Writes nodes/relationships with parameterized Cypher, using MERGE for categories/entities and CREATE for document instances. [hub.docker](https://hub.docker.com/_/neo4j)

- **Optional Obsidian Plugin (Companion)**  
  - Obsidian vault is used as source/target directory; plugin triggers indexing and shows graph views via existing Neo4j graph plugins. [github](https://github.com/zag/semantic-markdown-converter)

***

## 3. Functional Requirements

### Core CLI

- Required arguments:
  - `SOURCE_DIRECTORY`: directory containing raw documents.  
  - `TARGET_DIRECTORY`: root directory where organized folders are created.

- Behavior:
  1. Scan `SOURCE_DIRECTORY` for supported file types (PDF, DOCX, PPTX, XLSX, MD, TXT, HTML). [datacamp](https://www.datacamp.com/tutorial/docling)
  2. For each file:
     - Parse to Markdown using Docling (PyPdfium2 backend, optional OCR off for speed). [docling](https://docling.ai/)
     - Send truncated Markdown (e.g. 4000–8000 chars) to local LLM in LM Studio.  
     - Receive JSON with category, summary, entities, tags, confidence score.  
     - Write document + metadata into Neo4j graph.  
     - Decide target directory based on category/taxonomy.  
     - Create folder(s) and move/copy the file into `TARGET_DIRECTORY`.  
  3. Emit progress, logs, and a run manifest (JSON) for auditability.

### Modes

- `organize-docs`: full pipeline, including moves.  
- `index-only`: skip relocation; only parse + LLM + graph write.  
- `dry-run`: simulate moves, log proposed targets, but do not relocate.  
- `qa` (future): run semantic queries/Q&A over indexed docs via Neo4j + LLM.

***

## 4. Data Model & Neo4j Schema

### Node Types

- `Document`  
  - Properties: `id`, `path`, `filename`, `extension`, `summary`, `category_primary`, `categories_secondary`, `created_at`, `modified_at`, `hash`, `confidence`.  
- `Category`  
  - Properties: `name`, `description`, `slug`.  
- `Entity`  
  - Properties: `name`, `type` (Person, Organization, Concept, Project, Disease, etc.).  
- `Tag`  
  - Properties: `name`.  
- `SourceDirectory`  
  - Properties: `path`, `label`.  
- `ModelRun`  
  - Properties: `run_id`, `timestamp`, `model_name`, `model_version`, `source_dir`, `target_dir`, `config_hash`.  

### Relationships

- `(:Document)-[:BELONGS_TO]->(:Category)` (primary; optionally multiple secondary).  
- `(:Document)-[:MENTIONS]->(:Entity)` (per entity extracted).  
- `(:Document)-[:TAGGED_AS]->(:Tag)`.  
- `(:Document)-[:INGESTED_FROM]->(:SourceDirectory)`.  
- `(:ModelRun)-[:PROCESSED]->(:Document)` (for audit & reproducibility).  

This schema supports queries like:

- “All anticoagulation therapy documents in 2024 tagged as ‘clinical notes’.”  
- “Show all documents mentioning ‘skyrmions’ and related categories.”  
- “List documents processed in the last run where confidence < 0.7.”

***

## 5. LM Studio & Docling Integration

### LM Studio

- Start local server: `lms server start --port 1234` or via Developer tab. [lmstudio](https://lmstudio.ai/llms-full.txt)
- Use OpenAI‑compatible client:

  - `base_url="http://localhost:1234/v1"`  
  - `api_key="lm-studio"` (dummy constant, LM Studio ignores it by default). [lmstudio](https://lmstudio.ai/llms-full.txt)

- Inference call:

  - System prompt:  
    - “You are a JSON‑only semantic router. Given Markdown content, output a strict JSON object with category, summary, entities, tags, and confidence. Do not include prose outside JSON.”  
  - User content: truncated Markdown.  
  - Model: small instruction model (e.g. `gemma-2-2b-it-GGUF` or equivalent locally loaded in LM Studio). [lmstudio](https://lmstudio.ai/llms-full.txt)

### Docling

- Use `DocumentConverter` from IBM Docling to convert input files to Markdown. [docling-project.github](https://docling-project.github.io/docling/reference/document_converter/)
- Configure Docling for speed:

  - Use `PdfFormatOption` with pipeline options that disable heavy layout analysis if not needed (skip full table structure, images for fast runs).  
  - Explicitly set PyPdfium2 backend via Docling’s `PdfPipelineOptions` + `InputFormat.PDF` configuration. [datacamp](https://www.datacamp.com/tutorial/docling)

- For supported formats: PDF, DOCX, PPTX, XLSX, HTML, Markdown. [docling](https://docling.org/)

***


## 6. Technical Implementation Plan (Revised MVP)

> **Note:** The architecture and design have been significantly improved following a design review. Please see [Design_Decisions.md](./Design_Decisions.md) for the full breakdown of taxonomy binding, hierarchical chunking, tiered models, caching, and safety rules.
> 
> To ensure steady progress, development is split into phases. Phase 1 focuses on a stable, single-pass MVP.

### Phase 1 – Environment & Services

1. **Docker Compose Orchestration (`docker-compose.yml`)**
   - Run Neo4j locally with ports 7474 (HTTP) and 7687 (Bolt).
   - Configure volume mounts (`./neo4j_data:/data`) for persistence and add healthchecks.

2. **Python Project Setup (`pyproject.toml`)**
   - Dependencies: `typer`, `docling`, `neo4j`, `openai`, `rich`, `pydantic`, `pyyaml`, `structlog`.
   - Entrypoint: `organize-docs = "semantic_organizer.cli:app"`.

3. **LM Studio Setup**
   - Install LM Studio and start the local server on port 1234.
   - Load a compatible model (e.g., Qwen 2.5 7B Instruct) as the default for structured JSON output.

### Phase 2 – MVP Core Modules

#### 2.1 `config.py` & `taxonomy.py`
- Load global config (e.g., `semantic-organizer.toml`).
- Parse and validate `taxonomy.yaml`.
- Generate the dynamic JSON Schema enum for the LLM based on `category_id` slugs.

#### 2.2 `parser.py` (Document Ingestion)
- Implement `extract_text(file_path)` using IBM Docling.
- Extract basic PDF content and export to Markdown. (Advanced hierarchical chunking is deferred to Phase 2).

#### 2.3 `llm.py` (Semantic Extraction)
- Initialize the OpenAI-compatible client (`localhost:1234`).
- Send the Markdown to the LLM with the JSON Schema constraint generated by `taxonomy.py`.
- Parse the output into a Pydantic `SemanticPayload` model (category, summary, entities, confidence).

#### 2.4 `graph.py` (Database Operations)
- Connect to Neo4j via Bolt.
- Implement a **per-document atomic transaction**:
  - `MERGE` the `Document` node, `Category` nodes, and `Entity` nodes.
  - Create relationships (e.g., `[:BELONGS_TO]`, `[:MENTIONS]`).

#### 2.5 `routing.py` & `sidecar.py` (Filesystem Relocation)
- Map the assigned `category_id` to a target folder.
- Implement **safe copy** (copy-by-default, append `_2` on collision, never overwrite).
- Write `.semantic.json` (machine-readable) and `.semantic.md` (human-readable) artifacts alongside the copied file.

#### 2.6 `cli.py` (Typer Orchestration)
- `organize-docs doctor`: Validates Docker, Neo4j, LM Studio, and model availability.
- `organize-docs organize`: Runs the pipeline with `--dry-run` and safe-copy support.
- Uses `rich` for UI and `structlog` for structured logging.

### Phase 3 – Future Enhancements (v0.2+)

Once the MVP is stable, the following features (detailed in `Design_Decisions.md`) will be layered on:
- **Hierarchical Chunking**: Structure-aware map/reduce via `chunker.py` and `aggregator.py`.
- **Tiered Model Routing**: 2B models for fast chunking, 7B/14B for synthesis.
- **Stage-level Caching**: SQLite cache for Docling outputs, chunks, and LLM responses.
- **Crash Recovery**: Run manifest for resuming interrupted batches.
- **Deduplication**: Content-hash based duplicate detection.
- **`reclassify` Command**: Fast re-routing of cached documents without re-parsing.
