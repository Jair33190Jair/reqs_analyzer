# Architecture Decision Record: Requirements Specification Quality Analyzer

## 1. System Overview

A tool that ingests requirements specification documents (PDF, Excel, DOCX), extracts and structures their content, assigns identifiers where missing, stores everything in a queryable database, and uses an LLM to iteratively review the specifications for errors, incompleteness, ambiguity, and quality issues — returning structured, displayable feedback.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INGESTION LAYER                             │
│  PDF / DOCX / XLSX  →  Extraction  →  Normalization  →  ID Gen     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         STORAGE LAYER                               │
│  Relational DB (metadata, IDs, lineage)  +  Vector DB (embeddings)  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         ANALYSIS LAYER                              │
│  LLM-driven review passes  →  Structured findings  →  Feedback DB  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         PRESENTATION LAYER                          │
│  API / CLI / Web UI  →  Formatted reports per your template         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Decision Log

### DEC-1: PDF Extraction Library

**Decision: Use `PyMuPDF` (fitz) as primary, with `pdfplumber` as secondary for table-heavy pages.**

| Option | Pros | Cons |
|---|---|---|
| **PyMuPDF (fitz)** | Very fast (C-based). Preserves layout, fonts, bounding boxes. Extracts images. Active maintenance. Can detect headings via font size/weight. | AGPL license (viral for distribution — fine for internal tools). Table extraction is mediocre without post-processing. |
| **pdfplumber** | Excellent table detection/extraction. Good spatial awareness of text. MIT license. | Slower than PyMuPDF. Less reliable on scanned/image PDFs. |
| **PyPDF2 / pypdf** | Pure Python, easy install. MIT license. | Poor layout preservation. No font metadata. Weak on complex PDFs. |
| **Unstructured.io** | Auto-detects doc types, extracts tables, titles, narratives. Handles many formats. | Heavy dependency. Opinionated chunking. Harder to customize extraction logic. Overkill if you want tight control. |
| **Amazon Textract / Azure Doc Intelligence** | Best accuracy on scanned/image PDFs. Handles handwriting. | Cloud dependency, cost per page, latency, data leaves your infra. |

**Reasoning:** For requirements specs (typically text-heavy, digitally created PDFs), PyMuPDF gives you the best speed-to-quality ratio. You get font metadata (crucial for detecting headings, section numbers, and requirement IDs) at near-native speed. pdfplumber fills the gap for tabular content. If your PDFs are scanned images, add `Tesseract OCR` as a fallback — but check this first since it changes the economics significantly.

---

### DEC-2: Excel Extraction Library

**Decision: Use `openpyxl` for `.xlsx` files.**

| Option | Pros | Cons |
|---|---|---|
| **openpyxl** | Full read/write. Handles styles, merged cells, formulas. Most popular. | `.xlsx` only (not `.xls`). |
| **pandas** | Quick read into DataFrames. Great for tabular analysis. | Loses structure (merged cells, formatting, sheet-level metadata). |
| **xlrd** | Reads legacy `.xls`. | Deprecated for `.xlsx`. Read-only. |

**Reasoning:** Requirements in Excel often use merged cells, color-coding, and multi-sheet structures. `openpyxl` preserves this structural information, which you'll need for intelligent extraction. Use `pandas` downstream for analysis once you've already parsed the structure. For legacy `.xls`, add `xlrd` as a conditional dependency.

---

### DEC-3: What Information and Metadata to Store

**Decision: Store at three granularity levels — Document, Section, and Requirement.**

#### Document-level metadata
- `doc_id` (UUID)
- Original filename, file hash (SHA-256 for dedup)
- Source format (PDF/XLSX/DOCX)
- Upload timestamp, version number
- Extraction timestamp, extraction quality score (confidence)

#### Section-level metadata
- `section_id` (generated or extracted)
- Parent `doc_id`
- Section title, hierarchy level (1, 1.1, 1.1.1)
- Page number(s) / sheet name (for traceability)
- Raw text content
- Section type classification (functional req, non-functional, constraint, definition, etc.)

#### Requirement-level metadata
- `req_id` (extracted or generated — see DEC-5)
- Parent `section_id`
- Requirement text (verbatim)
- Normalized/cleaned text
- Requirement type (functional, performance, security, interface, etc.)
- Priority/criticality if stated
- Status (draft, reviewed, approved — extracted if present)
- Cross-references (mentions of other requirements)
- Embedding vector (for semantic search and duplicate detection)

#### Why three levels?
Single-level (just requirements) loses context. Two levels (doc + requirement) makes it hard to detect section-level issues like "section 3.2 has no testability criteria." Three levels maps naturally to how specs are structured and lets the LLM reason at the right granularity.

---

### DEC-4: Chunking Strategy

**Decision: Structure-aware chunking by sections and requirements, NOT fixed-size or page-based.**

| Strategy | Pros | Cons |
|---|---|---|
| **Fixed-size chunks (e.g., 512 tokens)** | Simple. Predictable context window usage. | Splits requirements mid-sentence. Loses section context. Terrible for structured documents. |
| **Page-based chunks** | Easy to implement. Natural for PDFs. | Pages are arbitrary boundaries — a requirement can span pages. Tables get split. |
| **Section-based (chosen)** | Preserves semantic units. Respects document hierarchy. Requirements stay whole. Cross-references stay in context. | Harder to implement (need section detection logic). Some sections may exceed context window. |
| **Semantic chunking (e.g., LangChain SemanticChunker)** | Groups by meaning. | Unpredictable boundaries. May still split requirements. Adds embedding cost at ingest time. |

**Reasoning:** Requirements documents are *structured* documents. The structure IS the information. Chunking by section preserves the author's intended grouping. Within sections, individual requirements become atomic units. If a section is too large for a single LLM call (>~8K tokens), split it at requirement boundaries and include the section header as context in each sub-chunk.

#### Implementation approach
1. Detect headings using font metadata (PDF) or heading styles (DOCX) or row patterns (XLSX)
2. Build a hierarchical tree: Document → Sections → Subsections → Requirements
3. Each requirement is the atomic unit; each section is the context unit
4. When feeding the LLM, send section-level chunks with full section context (title, parent section, sibling requirements)

---

### DEC-5: Requirement ID Generation

**Decision: Detect existing IDs with regex + heuristics; generate hierarchical IDs for unidentified requirements.**

#### ID Detection
Use regex patterns for common formats:
- `REQ-NNN`, `FR-NNN`, `NFR-NNN`
- `[SECTION].[NUMBER]` (e.g., 3.2.1)
- `SRS-XXX-NNN`, `SYS-NNN`
- Custom patterns (configurable per project)

#### ID Generation for unlabeled requirements
Format: `{DOC_PREFIX}-{SECTION}-{SEQ}`

Example: Document "System_Requirements_v2.pdf", section 3.2, third requirement → `SRV2-3.2-003`

**Why not just UUIDs?** UUIDs are opaque. When a human sees `SRV2-3.2-003`, they know which document, which section, and roughly where to look. This is critical for your review feedback to be actionable. Store a UUID as the internal primary key, but use the human-readable ID in all user-facing output.

**Important edge case:** When a document is re-uploaded (new version), you need a strategy for ID stability. Use content hashing + fuzzy matching to map old IDs to new content, flagging any requirements that changed, were added, or were removed.

---

### DEC-6: LangChain vs. Direct LLM Calls

**Decision: Use LangChain only where it adds clear value (specifically: document loaders and output parsers). Use direct API calls for the core analysis loop.**

| Approach | Pros | Cons |
|---|---|---|
| **Full LangChain (chains, agents, memory)** | Rapid prototyping. Built-in document loaders for many formats. Output parsers for structured data. Large community. | Abstraction hides what's happening. Frequent breaking changes. Hard to debug. Performance overhead. Many layers of indirection for something that's conceptually "send prompt, parse response." |
| **Direct API calls (chosen for core logic)** | Full control over prompts, retries, cost. Easy to debug. No dependency churn. Can optimize token usage precisely. | More boilerplate. Need to build your own retry/fallback logic. |
| **LlamaIndex** | Purpose-built for document Q&A. Good indexing. | Even more opinionated than LangChain. Less flexible for custom analysis workflows. |

**Reasoning:** Your core workflow is not a generic RAG chatbot — it's a structured, repeatable analysis pipeline. You need precise control over:
- Which requirements the LLM sees in each call
- The system prompt for each review pass (completeness check vs. ambiguity check vs. consistency check)
- Token budget management (specs can be huge)
- Output parsing and validation

LangChain's document loaders save time at ingestion. Its `PydanticOutputParser` is genuinely useful for getting structured JSON from the LLM. But its chain/agent abstractions add complexity without proportional value for a pipeline that you'll run repeatedly and need to trust.

**Recommended hybrid approach:**
```
Ingestion:  LangChain document loaders (convenience)  
Chunking:   Custom (structure-aware, see DEC-4)  
Storage:    Direct DB + vector store calls  
Analysis:   Direct LLM API calls with hand-crafted prompts  
Parsing:    Pydantic models (with or without LangChain's parser)  
```

---

### DEC-7: Database Choice

**Decision: PostgreSQL with `pgvector` extension.**

| Option | Pros | Cons |
|---|---|---|
| **PostgreSQL + pgvector** | Single DB for structured data AND vectors. ACID transactions. Mature, well-understood. Rich querying (joins, aggregations). pgvector supports cosine similarity, L2, inner product. | pgvector is less optimized than dedicated vector DBs at >1M vectors. Requires PostgreSQL expertise. |
| **SQLite + ChromaDB** | Zero-config. SQLite is embedded. ChromaDB is easy for prototyping. | Two systems to sync. ChromaDB has limited filtering. Neither scales well. Hard to maintain consistency between them. |
| **PostgreSQL + Pinecone/Weaviate** | Best-in-class vector search at scale. Managed infra. | Two systems. Cost. Network latency for vector queries. Overkill for <100K documents. |

**Reasoning:** For a requirements database, you'll have thousands to tens of thousands of requirements, not millions. pgvector handles this comfortably. The massive advantage is having one source of truth: you can JOIN structured metadata with vector similarity in a single query. Example: "Find requirements similar to REQ-042 that are in the 'Security' category and were added in the last version." That's one SQL query, not an orchestrated call across two systems.

If you later grow beyond pgvector's performance ceiling, Pinecone/Weaviate can be added as a search index while PostgreSQL remains the system of record.

---

### DEC-8: LLM Choice for Analysis

**Decision: Use Claude (Sonnet) as the primary model via the Anthropic API, with a structured prompt strategy.**

| Option | Pros | Cons |
|---|---|---|
| **Claude Sonnet** | Excellent at structured analysis and instruction-following. Large context window (200K). Strong at identifying subtle issues. Good at maintaining consistent output formats. Cost-effective for batch analysis. | API dependency. Not open-source. |
| **GPT-4o** | Strong general reasoning. Well-established API. | Smaller context window. Can be more "creative" (less desirable for systematic review). Higher cost at scale. |
| **Local model (Llama 3, Mistral)** | No API cost. Data stays local. | Significantly weaker at nuanced requirements analysis. Needs GPU infrastructure. More prompt engineering to get structured output. |

**Reasoning:** Requirements analysis demands precision, not creativity. You need the model to systematically apply quality criteria and produce consistent, structured output. Claude's instruction-following and large context window are ideal — you can feed entire sections with full context. For cost optimization, use Haiku for simple classification tasks (requirement type, priority detection) and Sonnet for the actual quality analysis.

---

### DEC-9: Analysis Pass Strategy

**Decision: Multi-pass analysis with specialized prompts per quality dimension.**

Rather than asking the LLM "find all issues" in one shot, run focused passes:

#### Pass 1: Completeness Check
- Are all INCOSE/IEEE 830 recommended sections present?
- Are there requirements with missing rationale, priority, or acceptance criteria?
- Are there gaps in numbering or cross-references?

#### Pass 2: Ambiguity Detection
- Flag vague terms: "appropriate", "as needed", "etc.", "and/or", "TBD"
- Identify unmeasurable requirements ("the system shall be fast")
- Detect missing boundary conditions ("the system shall handle large files")

#### Pass 3: Consistency Check
- Contradictions between requirements (semantic similarity + LLM verification)
- Terminology inconsistency (same concept, different names)
- Unit/format inconsistencies

#### Pass 4: Testability Assessment
- Can each requirement be verified? How?
- Are acceptance criteria present and specific?

#### Pass 5: Cross-Reference Integrity
- Do all references point to existing requirements?
- Are there orphan requirements (nothing depends on them, they depend on nothing)?
- Circular dependencies?

**Why multi-pass?** Single-pass analysis suffers from attention dilution — the model tries to check everything and catches less. Focused passes with specific rubrics produce more thorough, consistent results. They're also independently testable and can be run in parallel.

---

### DEC-10: Output Format

**Decision: Pydantic models serialized as JSON, with a configurable rendering layer.**

```python
class Finding(BaseModel):
    finding_id: str                    # e.g., "F-001"
    req_id: str                        # Which requirement
    doc_id: str                        # Which document
    section_path: str                  # e.g., "3.2.1 Authentication"
    category: FindingCategory          # enum: AMBIGUITY, INCOMPLETENESS, INCONSISTENCY, etc.
    severity: Severity                 # enum: CRITICAL, MAJOR, MINOR, INFO
    title: str                         # One-line summary
    description: str                   # Detailed explanation
    original_text: str                 # The problematic text
    suggestion: str                    # Proposed improvement
    confidence: float                  # 0.0-1.0, model's confidence
    review_pass: str                   # Which pass found this
    related_findings: list[str]        # Links to related findings
    status: FindingStatus              # NEW, ACKNOWLEDGED, RESOLVED, REJECTED
```

**Why Pydantic?** Validation at the boundary. The LLM can return malformed JSON — Pydantic catches that immediately. It also gives you automatic serialization, OpenAPI schema generation (if you build an API), and type safety throughout your Python code.

**Rendering** is separate: the same `Finding` object can be rendered as a Markdown report, an HTML dashboard row, a JIRA ticket, or a JSON API response. Keep the analysis output format-agnostic.

---

### DEC-11: Embedding Model

**Decision: Use `text-embedding-3-small` (OpenAI) or `voyage-3-lite` (Voyage AI) for generating requirement embeddings.**

| Option | Pros | Cons |
|---|---|---|
| **text-embedding-3-small** | Good quality/cost ratio. 1536 dimensions. Widely used. Cheap. | API dependency. OpenAI ecosystem. |
| **voyage-3-lite** | Optimized for code and technical text. Good at short passages. | Smaller ecosystem. |
| **Local (all-MiniLM-L6-v2)** | Free. Fast. No API. | Lower quality, especially on technical domain text. 384 dimensions. |

**Reasoning:** Requirements are short, technical text — embedding quality matters for duplicate detection and semantic search. The API-based models are significantly better at capturing nuanced meaning differences between requirements. At the volume of a requirements database (thousands, not millions), the API cost is negligible. If data sovereignty is a concern, `all-MiniLM-L6-v2` is the best local fallback.

---

## 4. Project Structure

```
req-analyzer/
├── src/
│   ├── ingestion/
│   │   ├── extractors/          # PDF, DOCX, XLSX extractors
│   │   ├── normalizer.py        # Text cleaning, unicode normalization
│   │   ├── id_detector.py       # Regex + heuristic ID extraction
│   │   ├── id_generator.py      # Hierarchical ID generation
│   │   └── section_parser.py    # Heading detection, hierarchy building
│   ├── storage/
│   │   ├── models.py            # SQLAlchemy models
│   │   ├── vector_store.py      # pgvector operations
│   │   └── repository.py        # Data access layer
│   ├── analysis/
│   │   ├── passes/              # One module per review pass
│   │   │   ├── completeness.py
│   │   │   ├── ambiguity.py
│   │   │   ├── consistency.py
│   │   │   ├── testability.py
│   │   │   └── cross_references.py
│   │   ├── prompts/             # Prompt templates (version controlled!)
│   │   ├── llm_client.py        # Anthropic API wrapper with retry logic
│   │   └── finding_parser.py    # Pydantic output validation
│   ├── presentation/
│   │   ├── formatters/          # Markdown, HTML, JSON renderers
│   │   └── api.py               # FastAPI endpoints (optional)
│   └── config.py
├── tests/
├── prompts/                     # Prompt templates as files (not inline strings)
├── alembic/                     # DB migrations
└── pyproject.toml
```

---

## 5. Key Technical Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LLM hallucinating findings | False positives erode trust | Always include `original_text` so humans can verify. Add confidence scores. Run a "self-check" pass where the model validates its own findings. |
| Poor PDF extraction | Garbage in, garbage out | Log extraction confidence. Flag pages with low text extraction. Support manual correction. |
| Requirements span pages/sections | Incomplete extraction | Use overlap windows at section boundaries. Post-process to merge split requirements. |
| Prompt drift across versions | Inconsistent results over time | Version-control all prompts. Store prompt version with each finding. |
| Large documents exceed context | Truncated analysis | Section-level chunking with sliding context window. Include parent section summary for context. |
| ID instability across doc versions | Broken traceability | Content-hash-based matching + fuzzy text similarity for ID continuity. |

---

## 6. Recommended Technology Stack Summary

| Component | Choice | Alternative to Consider |
|---|---|---|
| Language | Python 3.11+ | — |
| PDF Extraction | PyMuPDF + pdfplumber | Unstructured.io |
| Excel Extraction | openpyxl | pandas (for analysis only) |
| DOCX Extraction | python-docx | pandoc |
| Database | PostgreSQL + pgvector | SQLite + ChromaDB (prototype only) |
| ORM | SQLAlchemy 2.0 | — |
| LLM (analysis) | Claude Sonnet via Anthropic API | GPT-4o |
| LLM (classification) | Claude Haiku | GPT-4o-mini |
| Embeddings | text-embedding-3-small | voyage-3-lite |
| Output Validation | Pydantic v2 | — |
| API (optional) | FastAPI | — |
| Task Queue (if needed) | Celery + Redis | — |

---

## 7. Implementation Priority (Suggested Order)

1. **Extraction pipeline** — Get PDF/DOCX/XLSX → structured text working reliably
2. **Section & requirement parser** — Detect structure, extract atomic requirements
3. **ID detection & generation** — So every requirement is addressable
4. **Database schema & storage** — Persist everything with proper relations
5. **Single analysis pass (ambiguity)** — Prove the LLM analysis loop end-to-end
6. **Output formatting** — Render findings in your desired display format
7. **Additional analysis passes** — Add completeness, consistency, etc.
8. **Embedding + semantic search** — Duplicate detection, cross-reference analysis
9. **Versioning & diffing** — Track changes between document versions
10. **UI / API** — Expose to end users
