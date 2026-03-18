# Project Plan — AI Requirements Analyzer Pipeline

**Strategy:** ship a working pipeline first, harden second.
**Key insight:** you have drafts for all 6 stages and a real test corpus.
The fastest path to value is end-to-end validation, not stage-by-stage perfection.

---

## Phase 0 — Architecture baseline (one-time, before coding)
> Design is done. One diagram to capture it, then freeze.

- [x] **0.0** `architecture/pipeline_overview.puml` — one diagram showing all 6 stages
      and the JSON artifact between each (e.g. S0 → `00_raw_extract.json` → S1).
      This is the single source of truth. Updated only if a stage interface changes.
      Each stage file gets a one-line header comment: `# See: architecture_v1.md`

---

## Phase 1 — Implement all pipeline stages (S0–S5)
> Nothing is implemented yet. Build each stage in pipeline order.
> Stage specs: `architecture_v1.md`

- [x] **1.1** `S0_extractor.py` — PDF ingestion, page+char limit enforcement
  - V2 adds: font, spatial information, reconstruct reading order,
  detect page structure, incl. tables. Haiku suppport for low for messy content, with warning to user and cost estimation. User confirms cost and precision comment.
- [x] **1.2** `S1_normalizer.py` — ligature replacement, dehyphenation, item ID and heading pattern recognition
  - V2 adds: exact labeled fields (attribute names e.g. test_method, acceptance_criteria, safety_level, rationale, upstram_link, extra_attrs)
- [x] **1.3** `S2_preflight.py` — gatekeeper logic (ID count, duplicate detection, messy content score threshold)
  - V2 adds: validate returned patternS (size, matches), validate exact fields' names + ask user
              if he is okay with the amount of requirements, chapters and total cost of the
              analysis.
- [x] **1.4** `S3_llm_structurer.py` — cheap LLM identifies structure (items, attributes and locations). Python resolves loc coordinates to verbatim content via map_content() and generates internal ids; validated against two schemas: llm_response (internal) and resolved (artifact).
  - V2 adds: strap context blocks to pass to the analyzer (non-llm), identify context_blocks with script
- [ ] **1.5** `S4_llm_analyzer.py` — Calls the analyzer
  - V2 adds: context caching for refining spec. Three independent identifiers govern change classification: item_id, gen_uid, gen_hierarchy_number -> new, content_changed,position_changed,unchanged,deleted then does different reactions on the anlyzer
- [ ] **1.6** `S5_renderer.py` — Jinja2 HTML report generation
- [ ] **1.8** Decide invocation strategy: how are stages chained?
  Options: a) shell script, b) Python `run_pipeline.py`, c) manual per-stage
  → write the decision down and implement it

---

## Phase 2 — Run end-to-end on one real spec
> Don't test in isolation. Run the full pipeline and see what breaks.

- [ ] **2.1** Run S0→S5 on `input/arvms_specs/01_arvms_spec_clean/` (cleanest input)
- [ ] **2.2** Fix every breakage before moving on
- [ ] **2.3** Verify all 5 intermediate artifacts are present and non-empty
- [ ] **2.4** Verify HTML report renders in a browser without errors

---

## Phase 3 — Stress the pipeline with the test corpus
> Your corpus already exists. Use it.

- [ ] **3.1** `00_arvms_spec` — baseline (has ligatures + hyphenation)
- [ ] **3.2** `02_arvms_spec_10_pages` — at page limit, must pass
- [ ] **3.3** `03_arvms_spec_11_pages` — exceeds limit, S0 must reject cleanly
- [ ] **3.4** `04_arvms_spec_30000p_chars` — at char limit
- [ ] **3.5** Fix any new breakages found

---

## Phase 4 — Targeted tests (only what matters)
> Don't test everything. Test the parts that are risky or have already broken.

**Test corpus:**
- 10–15 small specs (2–6 pages), 3 medium specs (15–30 pages)
- Must include: 1 born-digital PDF, 1 scanned PDF (expected reject), 1 table-heavy layout

**Deterministic stages (S0, S1, S2) — unit tests worth writing:**
- [ ] **4.1** S0: page limit, char limit, bad extension, file not found
  → S0 test plan already exists and passes manually — automate it with pytest
  → Each test file header: `# Acceptance criteria: architecture_v1.md`
- [ ] **4.2** S1: ligature replacement, dehyphenation, req ID preservation
- [ ] **4.3** S2: ID count, duplicate detection, score threshold gate

**LLM stages (S3, S5) — don't unit test with real LLM calls:**
- [ ] **4.4** Test with a fixture (saved real LLM response) to validate parsing/schema logic only

**Renderer (S6) — one test:**
- [ ] **4.5** Known analysis JSON → HTML contains all req IDs and issue counts

**Golden end-to-end criteria (per run):**
- All expected requirement IDs present in `03_llm_structured.json`
- All intermediate artifacts present and schema-valid
- HTML report renders in browser without manual edits

---

## Phase 5 — Security (focused, not exhaustive)
> Only the real risks for this tool.

- [ ] **5.1** S5 HTML output: escape all spec text (prevent XSS if report opened in browser)
- [ ] **5.2** S3/S4 prompt injection: verify spec content cannot override system prompt
- [ ] **5.3** `.env` / API keys: confirm they never appear in any artifact or log

---

## Phase 6 — Final hardening pass
> One sweep across all files, not per-stage.

- [ ] **6.1** Linter (ruff or flake8) — zero warnings across all 6 stage files
- [ ] **6.2** Type hints consistent across all stages
- [ ] **6.3** Architecture↔code check: every stage in `architecture_v1.md` has a matching file
       and its one-line header comment points to the right section
- [ ] **6.4** Every JSON schema referenced in the architecture exists on disk
- [ ] **6.5** `pipeline_overview.puml` still matches actual stage interfaces
- [ ] **6.6** `architecture_v1.md` Definition of Done checklist verified against real output

---

## What was deliberately left out and why

| Skipped | Why |
|---------|-----|
| Per-stage sequence diagrams | One pipeline overview diagram is enough; per-stage diagrams go stale fast |
| Scalability review | Explicitly out of scope for V1 (single-document, occasional-use tool) |
| Exhaustive edge case tests for LLM stages | LLM output is non-deterministic; schema validation is your real contract |
| Stage-by-stage security review | Only 3 real attack surfaces exist; reviewing 6 stages separately is redundant |
