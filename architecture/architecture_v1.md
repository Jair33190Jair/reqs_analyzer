# 📄 AI Specification Analysis Pipeline — V1 Architecture & Interface Specification

**Version:** v1.0.0
**Owner:** Jair Jimenez
**Date:** 2026-02-23
**Scope:** Embedded / System / Software Requirements Specifications (SRS, SyRS, SWRS) with structured requirement IDs (e.g., `SYS-FUNC-001`)

---

# 1️⃣ Purpose

This document defines the complete **V1 production-ready pipeline specification** for:

PDF/DOCX → Text Extraction → Normalization → Preflight → LLM Structuring → LLM Analysis → Human-Readable Report

The design prioritizes:

* ✅ Low testing cost
* ✅ Deterministic preprocessing
* ✅ Stable JSON contracts
* ✅ LLM usage only where necessary
* ✅ Sellable output (HTML report)
* ✅ Clear schema versioning

This is designed as an **engineering-grade pipeline**, not a prompt experiment.

---

# 2️⃣ High-Level Architecture

![Pipeline Overview](pipeline_overview.svg)

> Source: [`pipeline_overview_v1.puml`](pipeline_overview_v1.puml)

### Design Philosophy

* Layers 1–3 must be deterministic.
* LLM is never used to compensate for broken extraction.
* All intermediate artifacts are stored for traceability.
* Each stage has a strict interface contract.

---

# 3️⃣ Directory & Artifact Structure

```
pipeline_run/
  input/
    spec.pdf | spec.docx
  artifacts/
    00_raw_extract.json
    01_normalized.json
    02_after_preflight.json
    03_llm_structured.json
    04_llm_analyzed.json
    05_report.html
    05_report.pdf          (optional)
  logs/
    pipeline.log
```

All stages must be reproducible from stored artifacts.

---

# 4️⃣ Stage (0) Extractor

## Purpose

Extract raw per-page text from PDF

## Input

* Born-digital PDF

## Output → `00_raw_extract_<input_file_stem>.json`

@import "../pipeline_root/schemas/00_raw_extract.schema.v1.json"


## Acceptance Criteria

* Page order preserved
* No catastrophic column mixing
* Text non-empty for born-digital PDFs
* No requirement ID corruption

---

# 5️⃣ Stage (1) Normalizer

## Purpose

Reduce token waste and stabilize downstream parsing.

## Input

`00_raw_extract_<input_file_stem>.json`

## Output → `01_normalized_<input_file_stem>.json`

@import "../pipeline_root/schemas/01_normalized.schema.v1.json"

## Normalization Rules (V1)

### 1. Dehyphenation

Replace:

```
(\w)-\n(\w) → \1\2
```

### 2. Ligature Normalization

Replace:

* ﬀ → ff
* ﬁ → fi
* ﬂ → fl
* ﬃ → ffi
* ﬄ → ffl

---

# 6️⃣ Stage (2) Preflight — Cost Protection Layer

## Purpose

Avoid wasting money on broken input.

## Input → `01_normalized_text_<input_file_stem>.json`

## Output → `02_after_preflight_<input_file_stem>.json`

@import "../pipeline_root/schemas/02_after_preflight.schema.v1.json"

## Deterministic Checks

* Count requirements with regex from normalizer
* Count duplicates
* Count sections with regex from normalizer
* Detect suspicious table patterns

## Gate Policy

LLM is called only if:

* ≥ 5 requirements detected
* No unexplained duplicates
* Score ≥ 0.80

Otherwise:

* Abort LLM call
* Emit guidance

---

# 7️⃣ Stage (3) LLM Chunker

## Purpose

Convert normalized text into structured specification JSON.

## Input → `02_after_preflight_<input_file_stem>.json`

## Output → `03_llm_structured_<input_file_stem>.json`

Schema: `spec.schema.v1`

@import "../pipeline_root/schemas/03_llm_structured.schema.v1.json"

## Structurer Rules

* One object per requirement ID
* Preserve thresholds, units, operators
* Evidence must include page reference
* Strict valid JSON only
* No modification of content of any type

---

# 8️⃣ Stage (5) LLM Analyzer

## Purpose

Assess quality, completeness, safety, and sellable insights.

## Output → `04_llm_analyzed.json`

Schema: `analysis.schema.v1`

```json
{
  "meta": {
    "schema": "analysis.schema.v1",
    "doc_id": "arvms_srs_v1_2026-02-19",
    "analyzer_version": "v1",
    "timestamp": "2026-02-23T08:00:00+01:00"
  },
  "metrics": {
    "req_count": 42,
    "by_kind": {},
    "shall_ratio": 1.0
  },
  "issues": [
    {
      "issue_id": "ISS-0001",
      "item_id": "SYS-FUNC-002",
      "category": "verifiability",
      "severity": "medium",
      "message": "...",
      "suggested_fix": "..."
    }
  ]
}
```

## Categories

* verifiability
* ambiguity
* consistency
* completeness
* feasibility
* safety
* security
* performance
* traceability
* style

## Severity

* low
* medium
* high
* critical

## Analyzer Rules

* Each issue must reference an item_id or section_id
* Provide concrete suggested fix
* No generic advice
* Keep concise

---

# 9️⃣ Stage (5) Renderer — Sellable Output

## Purpose

Transform JSON into human-consumable report.

## Output

* `05_report.html` (mandatory)
* `05_report.pdf` (optional)

## Report Sections

1. Metadata
2. Metrics Dashboard
3. Requirements Table (sortable/filterable)
4. Issues grouped by severity
5. Appendix with evidence excerpts

## Design Notes

* Use deterministic templating (e.g., Jinja2)
* No AI calls during rendering
* HTML first, PDF optional

---

# 🔟 Operational Controls

* Hard max token limit
* Chunk by section if too large (Using chapters as sections)
* Always store raw artifacts
* Log LLM cost per run

---

# 1️⃣1️⃣ Definition of Done (V1)

For born-digital PDFs:

* ≥ 95% requirement ID extraction accuracy
* ≥ 90% correct section assignment
* Valid schema-compliant JSON
* HTML report fully renderable

Scanned PDFs:

* Correctly detected and rejected with guidance.

---

# 🚀 Strategic Outcome

This V1 pipeline is:

* Deterministic where possible
* Controlled in cost
* Architecturally clean
* Scalable to enterprise use
* Sellable as an “AI Requirements Quality Auditor”
