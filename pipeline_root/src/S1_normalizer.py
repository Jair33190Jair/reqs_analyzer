import json
import re
import logging
import sys
from collections import Counter
from pathlib import Path

OUTPUT_FILENAME = "02_normalized_text.json"

LIGATURE_MAP = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

# Matches both dash-separated (SYS-FUNC-001) and space-separated (SYS FUNC 001) IDs
_REQ_ID = re.compile(r'^SYS[-\s][A-Z]{2,8}[-\s]\d{3}$')


def _replace_ligatures(text: str) -> str:
    for lig, rep in LIGATURE_MAP.items():
        text = text.replace(lig, rep)
    return text


def _dehyphenate(text: str) -> str:
    """Remove soft line-break hyphens: word-\nword → wordword."""
    return re.sub(r'(\w)-\n(\w)', r'\1\2', text)


def _soft_join(text: str) -> str:
    """
    Join line N to line N+1 with a space when:
      - line N does not end in .  ;  :
      - line N+1 starts with a lowercase letter or digit
      - line N is not a standalone requirement ID
    """
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            can_join = (
                cur
                and nxt
                and not re.search(r'[.;:]\s*$', cur)
                and re.match(r'^[a-z0-9]', nxt)
                and not _REQ_ID.match(cur.strip())
            )
            if can_join:
                out.append(cur + ' ' + nxt)
                i += 2
                continue
        out.append(cur)
        i += 1
    return '\n'.join(out)


def _find_repeated_lines(pages: list[dict], threshold: int = 3) -> set[str]:
    """Return stripped lines that appear on `threshold` or more distinct pages."""
    per_page = [
        {ln.strip() for ln in p["text"].split('\n') if ln.strip()}
        for p in pages
    ]
    counter: Counter = Counter()
    for page_lines in per_page:
        for ln in page_lines:
            counter[ln] += 1
    return {ln for ln, n in counter.items() if n >= threshold}


def _strip_headers_footers(pages: list[dict]) -> list[dict]:
    """
    Heuristic strip:
      1. Standalone page-number lines (bare digits only).
      2. Lines that repeat on 3+ pages (document headers / footers).
    """
    repeated = _find_repeated_lines(pages)
    result = []
    for page in pages:
        cleaned = []
        for ln in page["text"].split('\n'):
            s = ln.strip()
            if re.fullmatch(r'\d+', s):   # standalone page number
                continue
            if s and s in repeated:        # repeated header / footer
                continue
            cleaned.append(ln)
        result.append({"page": page["page"], "text": '\n'.join(cleaned)})
    return result


def normalize(raw: dict, source_ref: str) -> dict:
    pages = _strip_headers_footers(raw["pages"])
    norm_pages = []
    for p in pages:
        text = _replace_ligatures(p["text"])
        text = _dehyphenate(text)
        text = _soft_join(text)
        norm_pages.append({"page": p["page"], "text": text})
    return {
        "source_ref": source_ref,
        "normalization": {
            "dehyphenation": True,
            "ligature_map": True,
            "line_joining": "soft",
            "header_footer_strip": "heuristic",
        },
        "pages": norm_pages,
    }


def save_result(input_path: Path) -> Path:
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)
    result = normalize(raw, source_ref=input_path.name)
    output_path = input_path.parent / OUTPUT_FILENAME
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return output_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if len(sys.argv) < 2:
        logging.error("Usage: python S1_normalizer.py <path_to_raw_extract.json>")
        sys.exit(1)
    try:
        out = save_result(Path(sys.argv[1]))
        logging.info(f"Saved to {out}")
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        sys.exit(1)
