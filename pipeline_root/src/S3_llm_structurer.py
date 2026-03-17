#!/usr/bin/env python3
"""
Script purpose: LLM-based structurer for requirements specification documents.
                Identifies section headings and spec items by location (page + line range),
                then resolves loc coordinates to verbatim text via map_content().
Input:  01_normalized.json   (S1 output)
Output: 03_llm_structured.json
  - LLM response validated against 03_llm_structured.01_llm_response.schema.v1.json
  - Enriched artifact validated against 03_llm_structured.02_resolved.schema.v1.json
"""
# See: ../../architecture/architecture_v1.md

import json
import logging
import re
import sys
from pathlib import Path

import anthropic
import jsonschema
from dotenv import load_dotenv

load_dotenv()

_SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"
_LLM_RESPONSE_SCHEMA = json.loads((_SCHEMAS_DIR / "03_llm_structured.01_llm_response.schema.v1.json").read_text(encoding="utf-8"))
_ARTIFACT_SCHEMA = json.loads((_SCHEMAS_DIR / "03_llm_structured.02_resolved.schema.v1.json").read_text(encoding="utf-8"))

_SYSTEM = """\
You are an expert requirements document parser.

Your task: given a numbered requirements specification document, identify its structure and output ONLY valid JSON — no markdown fences, no explanation.

HEADING DETECTION:
{heading_instruction}

SPEC ITEM DETECTION:
{item_instruction}

OUTPUT SCHEMA (conform to this exactly — field descriptions are behavioral instructions, not documentation):
{schema}"""
###TODO(V2): Skip pagges shall have line precision


# --- Helpers ---

def _heading_instruction(heading_pattern: str | None) -> str:
    """Input: heading regex from S1 normalization, or None for raw specs.
    Output: instruction string injected into the LLM system prompt."""
    if heading_pattern:
        return (
            f"A heading line matches this regex: {heading_pattern}\n"
            "Emit a section entry for each line that matches. Do not emit sections for non-matching lines."
        )
    return (
        "No heading pattern was detected in this document. Identify headings semantically:\n"
        "- Short line (typically ≤ 60 characters)\n"
        "- Title case, sentence case, or ALL CAPS\n"
        "When uncertain, prefer not emitting a section over emitting a false one."
        ###TODO(V2): Once we include font extraction in the extractor we can add the font differentition here
    )


def _item_instruction(item_id_pattern: str | None) -> str:
    """Input: item ID regex from S1 normalization, or None for raw specs.
    Output: instruction string injected into the LLM system prompt."""
    if item_id_pattern:
        return (
            f"Spec items have IDs matching this regex: {item_id_pattern}\n"
            "Each item starts at the line containing its ID and ends at the line immediately before the next item ID or heading."
        )
    return (
        "This is a raw specification — no formal requirement IDs exist.\n"
        "Identify spec items as contiguous blocks of text that express a distinct engineering statement:\n"
        "- A system capability or behavior (look for 'shall', 'must', 'will', 'should')\n"
        "- A constraint, assumption, or interface definition\n"
        "Each item must be a single logical statement. Do not split a sentence across items. "
        "Do not merge statements that address different topics. Set item_id to null for all items."
    )


def _format_pages(pages: list[dict]) -> str:
    """Input: normalized pages list (each with 'page' and 'text' keys).
    Output: single string with all pages rendered as 1-based numbered lines for the LLM prompt."""
    parts = []
    for p in pages:
        lines = p["text"].split("\n")
        numbered = "\n".join(f"L{i + 1}: {line}" for i, line in enumerate(lines))
        parts.append(f"=== PAGE {p['page']} ===\n{numbered}")
    return "\n\n".join(parts)


def _call_llm(system_prompt: str, user_message: str) -> tuple[str, dict]:
    """Input: fully rendered system and user prompt strings.
    Output: (raw_response, parsed JSON dict).
    Raises ValueError on unparseable response."""
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    raw_response = message.content[0].text.strip()
    cleaned = re.sub(r"```json\s*([\s\S]*?)\s*```", r"\1", raw_response).strip()
    try:
        return raw_response, json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned unparseable JSON: {exc}\nRaw response: {raw_response[:500]}") from exc


# --- Mid-level ---

def run_structurer(normalized: dict) -> tuple[str, dict]:
    """Input: parsed 01_normalized JSON dict.
    Output: (raw_response, 03_llm_structured dict) — not yet schema-validated."""
    normalization = normalized.get("normalization", {})
    source_ref = normalized["source_ref"]

    system_prompt = _SYSTEM.format(
        heading_instruction=_heading_instruction(normalization.get("heading_pattern")),
        item_instruction=_item_instruction(normalization.get("item_id_pattern")),
        schema=json.dumps(_LLM_RESPONSE_SCHEMA, indent=2),
    )
    raw_response, result = _call_llm(system_prompt, f"SOURCE_REF: {source_ref}\n\n{_format_pages(normalized['pages'])}")
    result["source_ref"] = source_ref  # enforce regardless of what the LLM produced
    return raw_response, result


def _resolve_loc(loc: dict, pages_with_lines: dict[int, list[str]]) -> str:
    """Input: a loc dict {page, line_start, line_end} and a mapping of page number → lines (0-indexed list).
    Output: the resolved text for that loc range (1-based, inclusive line numbers)."""
    lines = pages_with_lines.get(loc["page"], [])
    start = loc["line_start"] - 1  # convert to 0-based
    end = loc["line_end"]          # slice end is exclusive, so line_end (1-based inclusive) works as-is
    return "\n".join(lines[start:end])


def map_content(result: dict, normalized: dict) -> dict:
    """Input: validated 03_llm_structured dict and the source 01_normalized dict.
    Output: enriched copy of result where every section and spec_item gains a
    'content' field — the verbatim text resolved from its loc coordinates."""
    pages_with_lines: dict[int, list[str]] = {
        p["page"]: p["text"].split("\n") for p in normalized["pages"]
    }
    enriched = dict(result)
    enriched["sections"] = [
        {**s, "content": _resolve_loc(s["loc"], pages_with_lines)}
        for s in result.get("sections", [])
    ]
    enriched["spec_items"] = [
        {**item, "content": _resolve_loc(item["loc"], pages_with_lines)}
        for item in result.get("spec_items", [])
    ]
    return enriched


def save_result(input_path: Path) -> Path:
    """Input: path to 01_normalized.json.
    Output: path to the written 03_llm_structured.json artifact.
    Always writes 03_llm_response.txt alongside for debugging.
    Raises FileNotFoundError or ValueError on any failure."""
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        normalized = json.load(f)
    if "pages" not in normalized or "normalization" not in normalized:
        raise ValueError(
            f"Expected a 01_normalized_*.json file (S1 output), got: {input_path.name}\n"
            "Usage: python S3_llm_chunker.py <path_to_01_normalized_*.json>"
        )
    raw_path = input_path.parent / f"03_llm_response.txt"

    raw_response, result = run_structurer(normalized)
    raw_path.write_text(raw_response, encoding="utf-8")

    try:
        jsonschema.validate(result, _LLM_RESPONSE_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"LLM response failed schema validation: {exc.message}\n"
            f"Raw LLM response saved to: {raw_path}"
        ) from exc

    enriched = map_content(result, normalized)

    try:
        jsonschema.validate(enriched, _ARTIFACT_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(
            f"Enriched artifact failed schema validation: {exc.message}\n"
            f"Raw LLM response saved to: {raw_path}"
        ) from exc

    output_path = input_path.parent / f"03_llm_structured.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)
    return output_path


# --- Top-level ---

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if len(sys.argv) < 2:
        logging.error("Usage: python S3_llm_chunker.py <path_to_normalized.json>")
        sys.exit(1)
    try:
        out = save_result(Path(sys.argv[1]))
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        logging.info(f"Saved to {out}")
        logging.info(
            f"Chunked: {len(data['sections'])} sections, "
            f"{len(data['spec_items'])} spec items, "
            f"skip_pages={data.get('skip_pages', [])}"
        )
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
