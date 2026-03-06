# See: ../../architecture/architecture_v1.md
import json
import logging
import re
import sys
from pathlib import Path

import jsonschema

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "02__after_preflight.schema.v1.json"

MIN_REQUIREMENTS = 5
MIN_SCORE = 0.80


def _collect_items(pages: list[dict], pattern: re.Pattern) -> list[str]:
    ids = []
    for page in pages:
        for line in page["text"].split("\n"):
            s = line.strip()
            if s and pattern.match(s):
                ids.append(s)
    return ids


def _collect_sections(pages: list[dict], pattern: re.Pattern | None) -> list[str]:
    if pattern is None:
        return []
    sections = []
    for page in pages:
        for line in page["text"].split("\n"):
            s = line.strip()
            if s and pattern.match(s):
                sections.append(s)
    return sections


def _detect_table_layout(pages: list[dict]) -> bool:
    """Flag if >20% of non-empty lines show tabular alignment (tabs or 3+ consecutive spaces)."""
    total = tab_lines = 0
    for page in pages:
        for line in page["text"].split("\n"):
            if not line.strip():
                continue
            total += 1
            if "\t\t" in line or re.search(r" {3,}", line):
                tab_lines += 1
    return total > 0 and (tab_lines / total) > 0.20


def _compute_score(
    item_ids: list[str],
    duplicate_ids: list[str],
    duplicate_sections: list[str],
    possible_table_layout: bool,
) -> float:
    score = 1.0
    if len(item_ids) < MIN_REQUIREMENTS:
        score -= 0.30
    if duplicate_ids:
        score -= min(0.30, 0.05 * len(duplicate_ids))
    if duplicate_sections:
        score -= min(0.10, 0.02 * len(duplicate_sections))
    if possible_table_layout:
        score -= 0.10
    return round(max(0.0, score), 4)


def run_preflight(normalized: dict, source_ref: str) -> dict:
    normalization = normalized.get("normalization", {})
    pages = normalized.get("pages", [])

    item_id_str = normalization.get("item_id_pattern")
    heading_str = normalization.get("heading_pattern")

    if not item_id_str:
        raise ValueError("Normalized input has no item_id_pattern — cannot run preflight.")

    item_id_pattern = re.compile(item_id_str, re.IGNORECASE)
    heading_pattern = re.compile(heading_str, re.IGNORECASE) if heading_str else None

    item_ids = _collect_items(pages, item_id_pattern)
    sections = _collect_sections(pages, heading_pattern)

    unique_ids = list(dict.fromkeys(item_ids))
    duplicate_ids = sorted({id_ for id_ in item_ids if item_ids.count(id_) > 1})

    unique_sections = list(dict.fromkeys(sections))
    duplicate_sections = sorted({s for s in sections if sections.count(s) > 1})

    possible_table_layout = _detect_table_layout(pages)
    score = _compute_score(item_ids, duplicate_ids, duplicate_sections, possible_table_layout)

    passed = len(item_ids) >= MIN_REQUIREMENTS and not duplicate_ids and score >= MIN_SCORE
    actions = ["send_to_llm_structurer"] if passed else ["abort"]

    return {
        "doc_id": Path(source_ref).stem,
        "checks": {
            "item_id_count": len(item_ids),
            "unique_item_id_count": len(unique_ids),
            "duplicate_item_ids": duplicate_ids,
            "sections_count": len(sections),
            "unique_section_count": len(unique_sections),
            "duplicate_sections": duplicate_sections,
            "possible_table_layout": possible_table_layout,
        },
        "score": score,
        "pass": passed,
        "actions": actions,
    }


def save_result(input_path: Path) -> Path:
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        normalized = json.load(f)
    result = run_preflight(normalized, source_ref=input_path.name)
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(result, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Preflight output failed schema validation: {exc.message}") from exc
    stem = input_path.stem.removeprefix("01_normalized_")
    output_path = input_path.parent / f"02_after_preflight_{stem}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if len(sys.argv) < 2:
        logging.error("Usage: python S2_preflight.py <path_to_normalized.json>")
        sys.exit(1)
    try:
        out = save_result(Path(sys.argv[1]))
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        status = "PASS" if data["pass"] else "FAIL"
        logging.info(f"Saved to {out}")
        logging.info(f"Preflight {status} — score={data['score']}, ids={data['checks']['item_id_count']}")
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        sys.exit(1)
