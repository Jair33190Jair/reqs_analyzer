# See: ../../architecture/architecture_v1.md
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

import jsonschema

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "02_after_preflight.schema.v1.json"

MIN_SCORE = 0.70
# Hard gate: if more than this fraction of non-empty lines look like table/matrix rows,
# the document layout is too chaotic for the LLM to parse reliably.
MESSY_LAYOUT_THRESHOLD = 0.50


def _collect_items(pages: list[dict], pattern: re.Pattern | None) -> list[str]:
    """Collect all lines matching the item ID pattern. Returns empty list if no pattern."""
    if pattern is None:
        return []
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


def _detect_messy_layout(pages: list[dict]) -> tuple[int, int]:
    """
    Detect lines that are likely table/matrix rows or otherwise too chaotic for LLM parsing.

    A line is "messy" if it contains:
    - multiple consecutive tabs (typical of copy-pasted tabular data), or
    - 4+ consecutive spaces (PDF table column separators in extracted text).

    Returns (messy_lines, total_non_empty_lines).
    """
    total = messy = 0
    for page in pages:
        for line in page["text"].split("\n"):
            if not line.strip():
                continue
            total += 1
            if re.search(r"\t{2,}", line) or re.search(r" {4,}", line):
                messy += 1
    return messy, total


def _compute_score(
    dup_id_ratio: float,
    dup_section_ratio: float,
    messy_layout_ratio: float,
) -> float:
    """
    Compute a processability score in [0.0, 1.0].

    messy_layout_ratio is the dominant factor: it represents whether the LLM can parse
    the document at all. Duplicate IDs/sections are secondary quality signals.

    A document with no IDs (raw spec) gets no penalty — the LLM will structure it
    from scratch. Missing IDs are metadata, not a quality defect.
    """
    score = 1.0
    score -= 0.60 * messy_layout_ratio  # primary: LLM cannot parse tabular chaos
    score -= 0.30 * dup_id_ratio        # secondary: duplicates suggest extraction noise
    score -= 0.10 * dup_section_ratio   # minor: duplicate headings
    return round(max(0.0, score), 4)


def run_preflight(normalized: dict, source_ref: str) -> dict:
    normalization = normalized.get("normalization", {})
    pages = normalized.get("pages", [])

    item_id_pattern_str = normalization.get("item_id_pattern")  # None for raw specs without IDs
    heading_id_pattern_str = normalization.get("heading_pattern")

    item_id_pattern = re.compile(item_id_pattern_str, re.IGNORECASE) if item_id_pattern_str else None
    heading_pattern = re.compile(heading_id_pattern_str, re.IGNORECASE) if heading_id_pattern_str else None

    item_ids = _collect_items(pages, item_id_pattern)
    sections = _collect_sections(pages, heading_pattern)

    id_counts = Counter(item_ids)
    unique_ids = list(dict.fromkeys(item_ids))
    duplicate_ids = sorted(id_ for id_, n in id_counts.items() if n > 1)

    section_counts = Counter(sections)
    unique_sections = list(dict.fromkeys(sections))
    duplicate_sections = sorted(s for s, n in section_counts.items() if n > 1)

    messy_layout_lines, total_lines = _detect_messy_layout(pages)

    unique_id_count = len(unique_ids)
    unique_section_count = len(unique_sections)

    dup_id_ratio = len(duplicate_ids) / unique_id_count if unique_id_count else 0.0
    dup_section_ratio = len(duplicate_sections) / unique_section_count if unique_section_count else 0.0
    messy_layout_ratio = messy_layout_lines / total_lines if total_lines else 0.0

    score = _compute_score(dup_id_ratio, dup_section_ratio, messy_layout_ratio)

    # A document without requirement IDs is valid — the LLM will structure it from scratch.
    # The only hard blocker is a layout too chaotic for the LLM to interpret.
    has_item_ids = item_id_pattern is not None and unique_id_count > 0
    passed = messy_layout_ratio < MESSY_LAYOUT_THRESHOLD and score >= MIN_SCORE

    return {
        "doc_id": Path(source_ref).stem,
        "source_ref": source_ref,
        "checks": {
            "has_item_ids": has_item_ids,
            "item_id_count": len(item_ids),
            "unique_item_id_count": unique_id_count,
            "duplicate_item_ids": duplicate_ids,
            "sections_count": len(sections),
            "unique_section_count": unique_section_count,
            "duplicate_sections": duplicate_sections,
            "messy_layout_lines": messy_layout_lines,
            "total_lines": total_lines,
        },
        "score": score,
        "pass": passed,
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
    output_path = input_path.parent / f"02_after_preflight.json"
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
        logging.info(
            f"Preflight {status} — score={data['score']}, "
            f"has_item_ids={data['checks']['has_item_ids']}, "
            f"unique_ids={data['checks']['unique_item_id_count']}"
        )
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        sys.exit(1)
