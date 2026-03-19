# See: ../../architecture/architecture_v1.md
import json
import re
import logging
import sys
import time
from collections import Counter
from pathlib import Path

import anthropic
import jsonschema
from dotenv import load_dotenv
from llm_pricing import get_cost

_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "01_normalized.schema.v1.json"

load_dotenv()


LIGATURE_MAP = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}

_LLM_MODEL = "claude-haiku-4-5-20251001"
_LLM_MAX_TOKENS = 300

_DETECT_PATTERNS_SYSTEM = (
    "You are a regex expert analysing requirements documents. "
    "Given a sample of lines, identify two patterns:\n"
    "1. item_id: standalone item ID lines (e.g. REQ-001, SYS-FUNC-001, A-001, INFO-1243). "
    "The regex must match when the ENTIRE line is the ID (include ^ and $ anchors).\n"
    "2. heading: section or chapter heading lines (e.g. '1. Introduction', '3.2.1 Scope', "
    "'CHAPTER 1 - Overview'). The regex must match when the ENTIRE line is the heading "
    "(include ^ and $ anchors).\n"
    "Reply with ONLY a JSON object with keys 'item_id' and 'heading', "
    "each a valid regex JSON-encoded string (escape backslashes as \\\\), "
    'or "NONE" if the pattern cannot be identified.\n'
    'Example: {"item_id": "^[A-Z]+-[0-9]+$", "heading": "^[0-9]+([.][0-9]+)*[.]?[ ]+[^ ].*$"}'
)

def _clean_text(text: str) -> str:
    """Remove soft line-break hyphens: word-\nword → wordword."""
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    for lig, rep in LIGATURE_MAP.items():
        text = text.replace(lig, rep)
    return text



def _detect_patterns(pages: list[dict]) -> tuple[re.Pattern | None, re.Pattern | None]:
    """Sample lines from 3 pages around the middle of the document and ask the LLM to infer the item ID and heading patterns.

    Returns:
        (item_id_pattern, heading_pattern) — either may be None if the LLM could not identify it.
        A None item_id_pattern means the document is a raw spec without formal requirement IDs.
    """
    mid = len(pages) // 2
    sample_lines = []
    for page in pages[mid - 5: mid + 5]:
        for ln in page["text"].split('\n'):
            s = ln.strip()
            if s:
                sample_lines.append(s)

    sample = '\n'.join(sample_lines[:120])

    raw_response = ""
    try:
        client = anthropic.Anthropic()
        t0 = time.monotonic()
        message = client.messages.create(
            model=_LLM_MODEL,
            max_tokens=_LLM_MAX_TOKENS,
            system=_DETECT_PATTERNS_SYSTEM,
            messages=[{"role": "user", "content": f"Lines:\n{sample}"}],
        )
        usage = message.usage
        elapsed = time.monotonic() - t0
        try:
            cost = f"${get_cost(_LLM_MODEL, usage.input_tokens, usage.output_tokens):.6f}"
        except Exception:
            cost = "cost unknown"
        logging.info(f"[S1 LLM] {usage.input_tokens} in / {usage.output_tokens} out — {cost} — {elapsed:.1f}s")
        raw_response = message.content[0].text.strip()
        cleaned_response = re.sub(r"```json\s*([\s\S]*?)\s*```", r"\1", raw_response).strip()
        response_data = json.loads(cleaned_response)

        item_id_str = response_data.get("item_id", "Empty")
        heading_str = response_data.get("heading", "Empty")

        if item_id_str == "NONE":
            logging.info("LLM could not identify an item ID pattern; document will be processed as a raw spec.")
            item_id_pattern = None
        elif item_id_str == "Empty":
            raise ValueError(f"LLM left the pattern attribute empty: {response_data}")
        else:
            item_id_pattern = re.compile(item_id_str, re.IGNORECASE)
            logging.info(f"LLM detected item ID pattern: {item_id_str}")

        heading_pattern = None
        if heading_str not in ("NONE", "Empty"):
            heading_pattern = re.compile(heading_str, re.IGNORECASE)
            logging.info(f"LLM detected heading pattern: {heading_str}")
        else:
            logging.info("LLM could not identify a heading pattern; headings will not be detected.")

        return item_id_pattern, heading_pattern


    except (json.JSONDecodeError):
        raise ValueError(f"LLM returned unparseable response: {raw_response}")
    except re.error as exc:
        raise ValueError(f"LLM returned invalid regex: {exc}")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"LLM call failed: {e}")
    

def _find_repeated_lines(pages: list[dict], threshold: int = 3) -> set[str]:
    """Return stripped lines that appear on `threshold` or more distinct pages."""
    """s_ln = stripped line"""
    pages_line_list = [
        {s_ln for ln in p["text"].split('\n') if (s_ln:=ln.strip())} 
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
      - Lines that repeat on 3+ pages (document headers / footers).
    """
    repeated = _find_repeated_lines(pages)
    result = []
    for page in pages:
        cleaned = []
        for ln in page["text"].split('\n'):
            s = ln.strip()
            if s and s in repeated:
                continue
            cleaned.append(ln)
        result.append({"page": page["page"], "text": '\n'.join(cleaned)})
    return result


def _normalize(raw: dict, source_ref: str) -> dict:
    cleaned_pages = [{"page": p["page"], "text": _clean_text(p["text"])} for p in raw["pages"]]
    stripped_pages = _strip_headers_footers(cleaned_pages)
    item_id_pattern, heading_pattern = _detect_patterns(stripped_pages)
    return {
        "source_ref": source_ref,
        "normalization": {
            "dehyphenation": True,
            "ligature_map": True,
            "line_joining": "none",
            "header_footer_strip": "heuristic",
            "item_id_pattern": item_id_pattern.pattern if item_id_pattern else None,
            "heading_pattern": heading_pattern.pattern if heading_pattern else None,
        },
        "pages": stripped_pages,
    }


def save_result(input_path: Path) -> Path:
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)
    normalized = _normalize(raw, source_ref=input_path.name)
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(normalized, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Normalized output failed schema validation: {exc.message}") from exc
    output_path = input_path.parent / f"01_normalized.json"
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
