# reqs_analyzer

AI-powered review pipeline for embedded software and systems requirements documents.

Accepts a born-digital PDF specification, runs it through a deterministic preprocessing pipeline, then uses Claude (Anthropic) to structure its content and flag quality issues — producing a structured JSON output and (planned) an HTML report.

---

## Pipeline Overview

```
[Input: PDF spec]
       |
       v
  S0 — Extractor          Extract raw per-page text, compute SHA-256, detect format warnings
       |
       v
  S1 — Normalizer         Ligature repair, dehyphenation, soft line joining, header/footer strip
       |
       v
  S2 — Preflight          Requirement ID detection, duplicate check, score gate (LLM cost protection)
       |
       v
  S3 — LLM Structurer     Convert normalized text → structured spec JSON (Claude)
       |
       v
  S4 — LLM Analyzer       Quality review: flags ambiguity, safety gaps, verifiability issues (Claude)
       |
       v
  S5 — Renderer           Produce human-readable HTML/PDF report
```

Design principle: stages S0–S2 are fully deterministic. LLM is called only if preflight passes.

---

## Input Constraints (v1)

| Constraint     | Value                  |
|----------------|------------------------|
| Format         | Born-digital PDF       |
| Max pages      | 10                     |
| Max characters | 30,000                 |
| Requirement ID | `SYS-[A-Z]{2,8}-\d{3}` |

---

## Output Artifacts

Each stage writes an intermediate artifact to `pipeline_root/artifacts/<project>/`:

| File                    | Stage         | Contents                              |
|-------------------------|---------------|---------------------------------------|
| `01_raw_extract.json`   | S0 Extractor  | Per-page text, SHA-256, warnings      |
| `02_normalized_text.json` | S1 Normalizer | Cleaned text, normalization metadata |
| `03_after_preflight.json` | S2 Preflight  | Check results, score, gate decision  |
| `04_llm_structured.json`  | S3 Structurer | Structured spec (documents, chapters, requirements, info nodes) |
| `05_llm_analyzed.json`    | S4 Analyzer   | Flags, statistics, AI analysis summary |
| `06_report.html`          | S5 Renderer   | Human-readable report                |

---

## Requirements

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com)

---

## Setup

```bash
git clone <repo-url>
cd reqs_analyzer

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

---

## Usage

Run each stage from `pipeline_root/`:

```bash
cd pipeline_root

# S0 — Extract text from PDF
python src/S0_extractor.py input/<project>/<spec>.pdf

# S1 — Normalize extracted text
python src/S1_normalizer.py artifacts/<project>/01_raw_extract.json

# S2–S5 — In development (see Status below)
```

---

## Project Structure

```
reqs_analyzer/
  architecture/           Architecture diagrams and design docs (PlantUML)
  pipeline_root/
    src/
      S0_extractor.py     Stage 0 — PDF text extraction
      S1_normalizer.py    Stage 1 — Text normalization
      S2_preflight.py     Stage 2 — Preflight gate (planned)
      S3_llm_structurer.py  Stage 3 — LLM structuring (WIP)
      S4_llm_analyzer.py  Stage 4 — LLM analysis (planned)
      S5_renderer.py      Stage 5 — Report rendering (planned)
      prompts/            LLM prompt definitions
    artifacts/            Intermediate JSON outputs (gitignored in production)
    input/                Input PDF specs — see input/arvms_specs/ for examples
    tests/                Test plans and test inputs
  requirements.txt
  .env.example
```

---

## Status

| Stage | Name         | Status       |
|-------|--------------|--------------|
| S0    | Extractor    | Complete     |
| S1    | Normalizer   | Complete     |
| S2    | Preflight    | Planned      |
| S3    | LLM Structurer | WIP        |
| S4    | LLM Analyzer | Planned      |
| S5    | Renderer     | Planned      |

---

## Domain Context

This tool is designed for embedded systems and safety-critical software engineering, targeting documents that follow standards such as ISO 26262 and ASPICE. The LLM analysis prompt is scoped to flag:

- Verifiability / testability issues
- Ambiguity and underspecification
- Missing safety or ASIL context
- Traceability gaps
- Consistency problems across requirements

---

## License

MIT — see [LICENSE](LICENSE)

---

## uthor

This project was developed by Jair Jimenez, Systems & Software Architect 
specialized in AI-augmented embedded and safety-critical system development with ADAS expertise.

For consulting, customization, or enterprise integration inquiries:
📩 jairjimenezv@gmail.com
🌐 linkedin.com/in/jairjimenezv