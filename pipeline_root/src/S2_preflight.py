# See: ../../architecture/architecture_v1.md
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

import jsonschema

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "02_after_preflight.schema.v1.json"

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


def _detect_table_layout(pages: list[dict]) -> tuple[int, int]:
    """Return (table_layout_lines, total_non_empty_lines) for tabular alignment detection."""
    total = tab_lines = 0
    for page in pages:
        for line in page["text"].split("\n"):
            if not line.strip():
                continue
            total += 1
            if "\t\t" in line or re.search(r" {3,}", line):
                tab_lines += 1
    return tab_lines, total


def _compute_score(
    unique_ids: list[str],
    duplicate_ids: list[str],
    unique_sections: list[str],
    duplicate_sections: list[str],
    table_layout_lines: int,
    total_lines: int,
) -> float:
    score = 1.0

    unique_id_count = len(unique_ids)
    unique_section_count = len(unique_sections)

    dup_id_ratio = len(duplicate_ids) / unique_id_count if unique_id_count else 0.0
    dup_section_ratio = len(duplicate_sections) / unique_section_count if unique_section_count else 0.0
    table_layout_ratio = table_layout_lines / total_lines if total_lines else 0.0

    if unique_id_count < MIN_REQUIREMENTS:
        score -= 0.30
    score -= 0.30 * dup_id_ratio
    score -= 0.10 * dup_section_ratio
    score -= 0.10 * table_layout_ratio

    return round(max(0.0, score), 4)


def run_preflight(normalized: dict, source_ref: str) -> dict:
    normalization = normalized.get("normalization", {})
    pages = normalized.get("pages", [])

    item_id_pattern = normalization.get("item_id_pattern")
    heading_id_pattern = normalization.get("heading_pattern")

    item_id_pattern = re.compile(item_id_pattern, re.IGNORECASE)
    heading_pattern = re.compile(heading_id_pattern, re.IGNORECASE) if heading_id_pattern else None

    item_ids = _collect_items(pages, item_id_pattern)
    sections = _collect_sections(pages, heading_pattern)

    id_counts = Counter(item_ids)
    unique_ids = list(dict.fromkeys(item_ids))
    duplicate_ids = sorted(id_ for id_, n in id_counts.items() if n > 1)

    section_counts = Counter(sections)
    unique_sections = list(dict.fromkeys(sections))
    duplicate_sections = sorted(s for s, n in section_counts.items() if n > 1)

    table_layout_lines, total_lines = _detect_table_layout(pages)
    score = _compute_score(
        unique_ids, duplicate_ids, unique_sections, duplicate_sections, table_layout_lines, total_lines
    )

    passed = len(unique_ids) >= MIN_REQUIREMENTS and score >= MIN_SCORE

    return {
        "doc_id": Path(source_ref).stem,
        "checks": {
            "item_id_count": len(item_ids),
            "unique_item_id_count": len(unique_ids),
            "duplicate_item_ids": duplicate_ids,
            "sections_count": len(sections),
            "unique_section_count": len(unique_sections),
            "duplicate_sections": duplicate_sections,
            "table_layout_lines": table_layout_lines,
            "total_lines": total_lines,
        },
        "score": score,
        "pass": passed
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
        logging.info(f"Preflight {status} — score={data['score']}, unique_ids={data['checks']['unique_item_id_count']}")
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        sys.exit(1)
