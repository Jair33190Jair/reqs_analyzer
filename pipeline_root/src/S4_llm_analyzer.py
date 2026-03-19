#!/usr/bin/env python3
"""
Script purpose: LLM-based analyzer for individual requirement quality.
                Reviews each spec item against ASPICE/ISO 26262/ISO 29148 quality criteria.
Input:  03_llm_structured.json  (S3 output)
Output: 04_llm_analyzed.json
  - LLM response validated against 04_llm_analyzed.01_llm_response.schema.v1.json
  - Enriched artifact validated against 04_llm_analyzed.02_resolved.schema.v1.json
"""
# See: ../../architecture/architecture_v1.md

import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import jsonschema
from dotenv import load_dotenv
from llm_pricing import get_cost

load_dotenv()

_SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"
_LLM_RESPONSE_SCHEMA = json.loads((_SCHEMAS_DIR / "04_llm_analyzed.01_llm_response.schema.v1.json").read_text(encoding="utf-8"))
_ARTIFACT_SCHEMA = json.loads((_SCHEMAS_DIR / "04_llm_analyzed.02_resolved.schema.v1.json").read_text(encoding="utf-8"))

_LLM_MODEL = "claude-sonnet-4-6"
_LLM_MAX_TOKENS = 16000
_PROMPT_VERSION = "1.0"
_PASS = "INDIVIDUAL_QUALITY"

_SYSTEM = """\
You are an expert automotive systems and software architect performing a \
requirement quality review. You have deep expertise in ASPICE, ISO 26262, \
and ISO/IEC/IEEE 29148 requirement quality criteria.

Your task: Review each requirement individually for QUALITY defects.

## Quality Criteria (check each requirement against ALL of these)

1. **AMBIGUITY** — Contains vague/subjective terms ("appropriate", "timely", \
"sufficient", "properly", "real-time" without a numeric bound, "etc.", \
"and/or", "as needed"). Would two engineers implement this identically?

2. **TESTABILITY** — Can a concrete pass/fail test be written from this \
requirement alone? Are thresholds, conditions, and expected behaviors \
explicit enough to verify?

3. **ATOMICITY** — Does the requirement contain exactly ONE "shall" (or similar) \
statement? Multiple behaviors bundled in one requirement are a defect.

4. **OVERCONSTRAINT** — Does the requirement prescribe implementation \
(specific algorithms, specific HW components, internal architecture) when \
it should state the NEED instead? A system-level requirement should say \
WHAT, not HOW. Exception: if the constraint is genuinely necessary at \
system level (e.g., safety-critical timing).

5. **COMPLETENESS** — Is the requirement missing boundary conditions, \
operating modes, failure behavior, or environmental conditions that would \
be needed for implementation?

6. **TERMINOLOGY** — Does it use inconsistent terms (referring to the same \
thing with different names across the spec) or undefined domain terms?

## Rules
- Only flag REAL issues. Do not flag something just to generate output.
- Severity CRITICAL = blocks downstream work or has safety implications.
- Severity MAJOR = will likely cause rework or ambiguous implementation.
- Severity MINOR = improvement opportunity, wording clarification.
- Severity INFO = use only for type OBSERVATION.
- If a requirement has NO quality issues, do NOT include it in findings.
- Be specific in your description: quote the problematic word/phrase.
- Keep recommendations actionable and concrete.
- confidence: your self-assessed certainty in this finding (0.0–1.0). \
Below 0.6 means you are unsure — use type QUESTION instead of FINDING.
- reference: cite the relevant normative standard where applicable \
(e.g. "ISO 26262-8 §6.4.2.1", "ASPICE SWE.1.BP5"). Null if no specific clause applies.

## Identifying affected items
Each requirement in the input is labeled with its gen_uid, item_id, and gen_hierarchy_number.
For each finding, populate affected_items with these identifiers and role "primary".
If a finding involves a conflict between two items, list both: one as "primary" (the one with the issue), \
the other as "conflicting".

## Output Format
Return ONLY valid JSON — no markdown fences, no explanation.
Conform exactly to this schema:
{schema}"""


# --- Helpers ---

def _gen_find_id(source_ref: str, primary_item: dict, category: str) -> str:
    """Input: source_ref string, primary affected_item dict, category string.
    Output: finding ID of the form GF-XXXXXX (6 hex uppercase).
    Uses item_id when present, gen_uid otherwise.
    gen_hierarchy_number is intentionally excluded — position-only changes must not
    invalidate a finding's identity."""
    item_key = primary_item.get("item_id") or primary_item["gen_uid"]
    raw = f"{source_ref}|{item_key}|{category}|{_PASS}"
    return "GF-" + hashlib.sha256(raw.encode()).hexdigest()[:6].upper()


def _log_usage(input_tokens: int, output_tokens: int, elapsed: float) -> None:
    try:
        cost = f"${get_cost(_LLM_MODEL, input_tokens, output_tokens):.6f}"
    except Exception:
        cost = "cost unknown"
    logging.info(f"[S4 LLM] {input_tokens} in / {output_tokens} out — {cost} — {elapsed:.1f}s")


def _call_llm(system_prompt: str, user_message: str) -> tuple[str, dict]:
    """Input: fully rendered system and user prompt strings.
    Output: (raw_response, parsed JSON dict).
    Raises ValueError on unparseable response."""
    client = anthropic.Anthropic()
    t0 = time.monotonic()
    message = client.messages.create(
        model=_LLM_MODEL,
        max_tokens=_LLM_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    _log_usage(message.usage.input_tokens, message.usage.output_tokens, time.monotonic() - t0)
    raw_response = message.content[0].text.strip()
    cleaned = re.sub(r"```json\s*([\s\S]*?)\s*```", r"\1", raw_response).strip()
    try:
        return raw_response, json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned unparseable JSON: {exc}\nRaw response: {raw_response[:500]}") from exc


def preprocess_for_llm(structured: dict) -> list[dict]:
    """Input: S3 resolved artifact.
    Output: list of slim item dicts for the LLM prompt — only what it needs for quality review.
    Strips loc, extra_attrs, flags, source — the LLM does not need those for quality judgment."""
    section_lookup = {}
    for sec in structured.get("sections", []):
        section_lookup[sec["gen_hierarchy_number"]] = {
            "number": sec.get("spec_hierarchy_number"),
            "title": sec["title"],
        }

    items = []
    for item in structured.get("spec_items", []):
        parent_key = item["gen_hierarchy_number"].rsplit("-", 1)[0] if "-" in item["gen_hierarchy_number"] else None
        section_ctx = section_lookup.get(parent_key, {})

        # Strip the item_id prefix line from content (it's redundant with the label)
        content = item["content"]
        if item.get("item_id"):
            content = content.replace(item["item_id"] + "\n", "").strip()

        items.append({
            "gen_uid": item["gen_uid"],
            "item_id": item.get("item_id"),
            "gen_hierarchy_number": item["gen_hierarchy_number"],
            "classification": item.get("classification"),
            "item_type": item.get("item_type"),
            "section_title": section_ctx.get("title", "Unknown"),
            "section_number": section_ctx.get("number", ""),
            "content": content,
        })
    return items


def build_user_prompt(items: list[dict]) -> str:
    """Input: preprocessed item list.
    Output: user prompt string listing all requirements for review."""
    parts = [
        f"Review the following {len(items)} requirements for quality issues.",
        "---",
    ]
    for item in items:
        label = item["item_id"] or item["gen_hierarchy_number"]
        parts.append(
            f"[{label}] (gen_uid={item['gen_uid']}, gen_hierarchy_number={item['gen_hierarchy_number']}, "
            f"Section {item['section_number']} {item['section_title']}, "
            f"type: {item['item_type']}, classification: {item['classification']})\n"
            f"{item['content']}"
        )
    return "\n\n".join(parts)


# --- Mid-level ---

def run_analyzer(structured: dict) -> tuple[str, dict]:
    """Input: parsed 03_llm_structured JSON dict.
    Output: (raw_response, findings dict conforming to 04_llm_analyzed.01_llm_response)."""
    system_prompt = _SYSTEM.format(
        schema=json.dumps(_LLM_RESPONSE_SCHEMA, indent=2),
    )
    items = preprocess_for_llm(structured)
    user_prompt = build_user_prompt(items)
    return _call_llm(system_prompt, user_prompt)


def enrich_findings(raw_findings: dict, source_ref: str) -> dict:
    """Input: validated raw LLM findings dict, source_ref string.
    Output: resolved artifact matching 04_llm_analyzed.02_resolved schema —
    gen_find_id assigned, disposition initialized, stats computed."""
    findings = []
    for f in raw_findings.get("findings", []):
        # Find the primary affected item for gen_find_id computation
        primary = None
        for ai in f["affected_items"]:
            if ai["role"] == "primary":
                primary = ai
                break
        if primary is None:
            primary = f["affected_items"][0]

        gen_find_id = _gen_find_id(source_ref, primary, f["category"])

        findings.append({
            "gen_find_id": gen_find_id,
            "pass": _PASS,
            "type": f["type"],
            "category": f["category"],
            "severity": f["severity"],
            "affected_items": f["affected_items"],
            "description": f["description"],
            "recommendation": f.get("recommendation"),
            "reference": f.get("reference"),
            "confidence": f["confidence"],
            "disposition": {
                "status": "OPEN",
                "author_note": None,
                "resolved_in_version": None,
                "reviewed_by": None,
                "review_date": None,
            },
        })

    stats = {
        "total": len(findings),
        "by_severity": {
            "CRITICAL": sum(1 for f in findings if f["severity"] == "CRITICAL"),
            "MAJOR": sum(1 for f in findings if f["severity"] == "MAJOR"),
            "MINOR": sum(1 for f in findings if f["severity"] == "MINOR"),
            "INFO": sum(1 for f in findings if f["severity"] == "INFO"),
        },
        "by_type": {
            "FINDING": sum(1 for f in findings if f["type"] == "FINDING"),
            "QUESTION": sum(1 for f in findings if f["type"] == "QUESTION"),
            "OBSERVATION": sum(1 for f in findings if f["type"] == "OBSERVATION"),
        },
    }

    return {
        "source_ref": source_ref,
        "analysis_meta": {
            "pass": _PASS,
            "model": _LLM_MODEL,
            "prompt_version": _PROMPT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "doc_version": None,
        },
        "findings": findings,
        "stats": stats,
    }


def save_result(input_path: Path) -> Path:
    """Input: path to 03_llm_structured.json.
    Output: path to the written 04_llm_analyzed.json artifact.
    Always writes 04_llm_response.txt alongside for debugging.
    Raises FileNotFoundError or ValueError on any failure."""
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        structured = json.load(f)
    if "sections" not in structured or "spec_items" not in structured:
        raise ValueError(
            f"Expected a 03_llm_structured.json file (S3 output), got: {input_path.name}\n"
            "Usage: python S4_llm_analyzer.py <path_to_03_llm_structured.json>"
        )
    source_ref = structured.get("source_ref", input_path.name)
    raw_path = input_path.parent / "04_llm_response.txt"

    raw_response, result = run_analyzer(structured)
    raw_path.write_text(raw_response, encoding="utf-8")

    # Wrap in {"findings": [...]} if LLM returned a bare array
    if isinstance(result, list):
        result = {"findings": result}

    try:
        jsonschema.validate(result, _LLM_RESPONSE_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"LLM response failed schema validation: {exc.message}\n"
            f"Raw LLM response saved to: {raw_path}"
        ) from exc

    enriched = enrich_findings(result, source_ref)

    try:
        jsonschema.validate(enriched, _ARTIFACT_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"Enriched artifact failed schema validation: {exc.message}\n"
            f"Raw LLM response saved to: {raw_path}"
        ) from exc

    output_path = input_path.parent / "04_llm_analyzed.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)
    return output_path


# --- Top-level ---

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if len(sys.argv) < 2:
        logging.error("Usage: python S4_llm_analyzer.py <path_to_03_llm_structured.json>")
        sys.exit(1)
    try:
        out = save_result(Path(sys.argv[1]))
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        logging.info(f"Saved to {out}")
        logging.info(
            f"Analyzed: {data['stats']['total']} findings — "
            f"CRITICAL={data['stats']['by_severity']['CRITICAL']}, "
            f"MAJOR={data['stats']['by_severity']['MAJOR']}, "
            f"MINOR={data['stats']['by_severity']['MINOR']}"
        )
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
