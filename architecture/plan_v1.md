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

```
[Input Spec: PDF/DOCX]
        |
        v
(1) Extractor
        |
        v
(2) Normalizer
        |
        v
(3) Preflight (Gatekeeper)
        |
        v
(4) LLM Structurer
        |
        v
(5) LLM Analyzer
        |
        v
(6) Renderer (HTML/PDF)
```

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
    01_raw_extract.json
    02_normalized_text.json
    03_preflight.json
    04_spec.json
    05_analysis.json
    06_report.html
    06_report.pdf          (optional)
  logs/
    pipeline.log
```

All stages must be reproducible from stored artifacts.

---

# 4️⃣ Stage (1) Extractor

## Purpose

Extract raw per-page text from PDF or DOCX.

## Input

* Born-digital PDF (preferred)
* DOCX (preferred for premium tier)

## Output → `01_raw_extract.json`

```json
{
  "source": {
    "filename": "spec.pdf",
    "type": "pdf",
    "sha256": "<hash>",
    "page_count": 6
  },
  "pages": [
    { "page": 1, "text": "..." },
    { "page": 2, "text": "..." }
  ],
  "warnings": [
    "detected_ligatures",
    "line_hyphenation_present"
  ]
}
```

## Acceptance Criteria

* Page order preserved
* No catastrophic column mixing
* Text non-empty for born-digital PDFs
* No requirement ID corruption

---

# 5️⃣ Stage (2) Normalizer

## Purpose

Reduce token waste and stabilize downstream parsing.

## Input

`01_raw_extract.json`

## Output → `02_normalized_text.json`

```json
{
  "source_ref": "01_raw_extract.json",
  "normalization": {
    "dehyphenation": true,
    "ligature_map": true,
    "line_joining": "soft",
    "header_footer_strip": "heuristic"
  },
  "pages": [
    { "page": 1, "text": "..." }
  ]
}
```

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

### 3. Soft Line Join

Join lines only if:

* previous line does NOT end in `. : ;`
* next line starts lowercase or number

### 4. Preserve Requirement IDs

Never merge in a way that breaks:

```
SYS-[A-Z]{2,8}-\d{3}
```

---

# 6️⃣ Stage (3) Preflight — Cost Protection Layer

## Purpose

Avoid wasting money on broken input.

## Input

`02_normalized_text.json`

## Output → `03_preflight.json`

```json
{
  "doc_id": "auto_generated",
  "checks": {
    "req_id_count": 42,
    "unique_req_id_count": 42,
    "duplicate_req_ids": [],
    "missing_id_gaps": [],
    "section_detected": true,
    "possible_table_layout": false
  },
  "score": 0.92,
  "pass": true,
  "actions": ["send_to_llm_structurer"]
}
```

## Deterministic Checks

* Regex: `\bSYS-[A-Z]{2,8}-\d{3}\b`
* Count duplicates
* Detect numeric gaps
* Detect “shall” usage
* Basic section heading heuristic
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

# 7️⃣ Stage (4) LLM Structurer

## Purpose

Convert normalized text into structured specification JSON.

## Output → `04_spec.json`

Schema: `spec.schema.v1`

```json
{
  "meta": {
    "schema": "spec.schema.v1",
    "doc_id": "arvms_srs_v1_2026-02-19",
    "title": "...",
    "version": "1.0",
    "date": "2026-02-19",
    "author": "Jair Jimenez",
    "source": {
      "filename": "spec.pdf",
      "page_count": 6
    }
  },
  "structure": {
    "sections": [
      {
        "section_id": "3.1",
        "title": "Navigation",
        "path": ["3", "3.1"],
        "page_range": [2, 2]
      }
    ]
  },
  "requirements": [
    {
      "req_id": "SYS-FUNC-001",
      "kind": "functional",
      "shall": true,
      "text": "...",
      "section_id": "3.1",
      "evidence": {
        "page": 2,
        "quote": "short excerpt"
      }
    }
  ]
}
```

## Structurer Rules

* One object per requirement ID
* Preserve thresholds, units, operators
* Evidence must include page reference
* Strict valid JSON only
* No hallucinated IDs

---

# 8️⃣ Stage (5) LLM Analyzer

## Purpose

Assess quality, completeness, safety, and sellable insights.

## Output → `05_analysis.json`

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
      "req_id": "SYS-FUNC-002",
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

* Each issue must reference a req_id or section_id
* Provide concrete suggested fix
* No generic advice
* Keep concise

---

# 9️⃣ Stage (6) Renderer — Sellable Output

## Purpose

Transform JSON into human-consumable report.

## Output

* `06_report.html` (mandatory)
* `06_report.pdf` (optional)

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

# 🔟 V1 Test Strategy (Cost-Optimized)

## Corpus

* 10–15 small specs (2–6 pages)
* 3 medium specs (15–30 pages)
* Include:

  * 1 DOCX
  * 1 born-digital PDF
  * 1 scanned PDF (expected fail)
  * 1 table-heavy layout

## Deterministic Unit Tests

Extractor:

* Page count match
* Non-empty text

Normalizer:

* Ligatures removed
* Hyphen patterns reduced

Preflight:

* ID count correct
* Duplicate detection working

## Golden End-to-End Tests

* All expected requirement IDs present
* JSON schema valid
* HTML renders without manual edits

---

# 1️⃣1️⃣ Operational Controls

* Hard max token limit
* Chunk by section if too large (Using chapters as sections)
* Always store raw artifacts
* Log LLM cost per run

---

# 1️⃣2️⃣ Versioning Strategy

Schemas are versioned:

* `spec.schema.v1`
* `analysis.schema.v1`

Backward-compatible additions allowed.
Breaking changes require v2.

---

# 1️⃣3️⃣ Definition of Done (V1)

For born-digital PDFs and DOCX:

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

You now have a machine-grade contract for your AI specification analyzer.
