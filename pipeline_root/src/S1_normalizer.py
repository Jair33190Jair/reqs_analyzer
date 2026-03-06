# See: ../../architecture/architecture_v1.md
import json
import re
import logging
import sys
from collections import Counter
from pathlib import Path

import anthropic
import jsonschema
from dotenv import load_dotenv

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "01_normalized.schema.v1.json"

load_dotenv()


LIGATURE_MAP = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

_DETECT_PATTERNS_SYSTEM = (
    "You are a regex expert analysing requirements documents. "
    "Given a sample of lines, identify two patterns:\n"
    "1. item_id: standalone item ID lines (e.g. REQ-001, SYS-FUNC-001, A-001, INFO-1243). "
    "The regex must match when the ENTIRE line is the ID (include ^ and $ anchors).\n"
    "2. heading: section or chapter heading lines (e.g. '1. Introduction', '3.2.1 Scope', "
    "'CHAPTER 1 - Overview'). The regex must match when the ENTIRE line is the heading "
    "(include ^ and $ anchors).\n"
    "Reply with ONLY a JSON object with keys 'item_id' and 'heading', each a valid Python "
    "regex string or the word NONE if the pattern cannot be identified.\n"
    'Example: {"item_id": "^[A-Z]+-[0-9]+$", "heading": "^[0-9]+(\\.[0-9]+)*\\.?\\s+\\S.*$"}'
)



def detect_patterns(pages: list[dict]) -> tuple[re.Pattern, re.Pattern | None]:
    """Sample lines from the first 3 pages and ask the LLM to infer the item ID and heading patterns.

    Returns:
        (item_id_pattern, heading_pattern) — heading_pattern is None if the LLM replied NONE.
    """
    sample_lines = []
    for page in pages[:3]:
        for ln in page["text"].split('\n'):
            """By default, function strips whitespaces at beginning and end of the line
            This way, only non-empty lines are kept in the sample => Save tokens and avoid confusing
            the LLM"""
            s = ln.strip()
            if s:
                sample_lines.append(s)

    sample = '\n'.join(sample_lines[:120])

    raw_response = ""
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=_DETECT_PATTERNS_SYSTEM,
            messages=[{"role": "user", "content": f"Lines:\n{sample}"}],
        )
        raw_response = message.content[0].text.strip()
        data = json.loads(raw_response)

        item_id_str = data.get("item_id", "NONE")
        heading_str = data.get("heading", "NONE")

        if item_id_str == "NONE":
            raise ValueError("LLM could not identify an item ID pattern.")
        item_id_pattern = re.compile(item_id_str, re.IGNORECASE)
        logging.info(f"LLM detected item ID pattern: {item_id_str}")

        heading_pattern = None
        if heading_str != "NONE":
            heading_pattern = re.compile(heading_str, re.IGNORECASE)
            logging.info(f"LLM detected heading pattern: {heading_str}")
        else:
            logging.info("LLM could not identify a heading pattern; headings will not be detected.")

        return item_id_pattern, heading_pattern

    except (json.JSONDecodeError, KeyError):
        raise ValueError(f"LLM returned unparseable response: '{raw_response}'.")
    except re.error as exc:
        raise ValueError(f"LLM returned invalid regex: {exc}.")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"LLM call failed: {e}.")

def _clean_text(text: str) -> str:
    """Remove soft line-break hyphens: word-\nword → wordword."""
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    for lig, rep in LIGATURE_MAP.items():
        text = text.replace(lig, rep)
    return text


def _soft_join(text: str, item_id_pattern: re.Pattern, heading_pattern: re.Pattern | None) -> str:
    """
    Join line N to line N+1 with a space when:
      - line N does not end in .  ;  :
      - line N+1 starts with a lowercase letter
      - neither line is a standalone item ID or heading

    This should be very conservative and only join lines where it is certain they belong together.
    """
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            cur_s = cur.strip()
            nxt_s = nxt.strip()
            is_structural = (
                item_id_pattern.match(cur_s)
                or item_id_pattern.match(nxt_s)
                or (heading_pattern and heading_pattern.match(cur_s))
                or (heading_pattern and heading_pattern.match(nxt_s))
            )
            can_join = (
                cur
                and nxt
                and not re.search(r'[.;:]\s*$', cur)
                and re.match(r'^[a-z]', nxt)  # Only if next word starts with lowercase
                and not is_structural
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
    # LLM detects item ID and heading patterns for structuring the document
    stripped_pages = _strip_headers_footers(cleaned_pages)
    item_id_pattern, heading_pattern = detect_patterns(stripped_pages)
    norm_pages = []
    for p in stripped_pages:
        text = _soft_join(p["text"], item_id_pattern, heading_pattern)
        norm_pages.append({"page": p["page"], "text": text})
    return {
        "source_ref": source_ref,
        "normalization": {
            "dehyphenation": True,
            "ligature_map": True,
            "line_joining": "soft",
            "header_footer_strip": "heuristic",
            "item_id_pattern": item_id_pattern.pattern,
            "heading_pattern": heading_pattern.pattern if heading_pattern else None,
        },
        "pages": norm_pages,
    }


def save_result(input_path: Path) -> Path:
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)
    normalized = normalize(raw, source_ref=input_path.name)
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(normalized, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Normalized output failed schema validation: {exc.message}") from exc
    source_stem = Path(raw["source"]["filename"]).stem
    output_path = input_path.parent / f"01_normalized_{source_stem}.json"
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
