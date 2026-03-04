import json
import re
import logging
import sys
from collections import Counter
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

OUTPUT_FILENAME = "02_normalized_text.json"

LIGATURE_MAP = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

_DETECT_REQID_SYSTEM = (
    "You are a regex expert analysing requirements documents. "
    "Given a sample of lines, identify the pattern used for standalone requirement IDs "
    "(e.g. REQ-001, SYS-FUNC-001, A-001, etc.). "
    "Reply with ONLY a valid Python regex pattern that matches those IDs when the entire "
    "line is the ID (include ^ and $ anchors). "
    "If you cannot identify a clear pattern, reply with the single word: NONE."
)


def detect_req_id_pattern(pages: list[dict]) -> re.Pattern:
    """Sample lines from the first 3 pages and ask the LLM to infer the req ID pattern."""
    sample_lines = []
    for page in pages[:3]:
        for ln in page["text"].split('\n'):
            """By default, function streeps whitespaces at beginning and end of the line
            This way, only non-empty lines are kept in the sample => Save tokens and avoid confusing
            the LLM"""
            s = ln.strip()
            if s:
                sample_lines.append(s)

    sample = '\n'.join(sample_lines[:120])

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_DETECT_REQID_SYSTEM,
            messages=[{"role": "user", "content": f"Lines:\n{sample}"}],
        )
        pattern_str = message.content[0].text.strip()
        if pattern_str == "NONE":
            raise ValueError("LLM could not identify a req ID pattern.")
        compiled = re.compile(pattern_str, re.IGNORECASE)
        logging.info(f"LLM detected req ID pattern: {pattern_str}")
        return compiled
    except re.error:
        raise ValueError(f"LLM returned invalid regex '{pattern_str}'.")
    except Exception as e:
        raise ValueError(f"LLM call failed: {e}.")

def _clean_text(text: str) -> str:
    """Remove soft line-break hyphens: word-\nword → wordword."""
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    for lig, rep in LIGATURE_MAP.items():
        text = text.replace(lig, rep)
    return text


def _soft_join(text: str, req_id_pattern: re.Pattern) -> str:
    """
    Join line N to line N+1 with a space when:
      - line N does not end in .  ;  :
      - line N+1 starts with a lowercase letter
      - line N is not a standalone requirement ID

    This should be very conservative and only join lines where it is certain they belong together.
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
                and re.match(r'^[a-z]', nxt) "Only if next word starts with lowercase"
                and not req_id.match(cur.strip())
                and not req_id.match(nxt.strip())
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
    pages_line_list = [
        {s_ln for ln in p["text"].split('\n') if (s_ln:=ln.strip())} """s_ln = stripped line"""
        for p in pages
    ]
    counter: Counter = Counter()
    for page_line in pages_line_list:
        for ln in page_line:
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
            if s and s in repeated:        # repeated header / footer
                continue
            cleaned.append(ln)
        result.append({"page": page["page"], "text": '\n'.join(cleaned)})
    return result


def normalize(raw: dict, source_ref: str) -> dict:
    # clean once, use everywhere
    cleaned_pages = [{"page": p["page"], "text": _clean_text(p["text"])} for p in raw["pages"]]
    # LLM detects the req ID pattern for identifying requirements
    stripped_pages = _strip_headers_footers(cleaned_pages)
    req_id_pattern = detect_req_id_pattern(stripped_pages)
    norm_pages = []
    for p in stripped_pages:
        text = _soft_join(p["text"], req_id_pattern)
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
    cleaned = _clean_text(raw)
    normalized = normalize(cleaned, source_ref=input_path.name)
    output_path = input_path.parent / OUTPUT_FILENAME
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)
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
