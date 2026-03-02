import fitz
import json
import hashlib
import jsonschema
import logging
import sys
import re
from pathlib import Path

# --- Configuration ---
SCHEMA_PATH = Path(__file__).parent.parent / "artifacts" / "01_raw_extract.json"
INPUT_DIR   = Path("input")
OUTPUT_DIR  = Path("artifacts")
MAX_PAGES   = 10
MAX_CHARS   = 30_000


def load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)

def compute_sha256(pdf_path: str) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_warnings(text: str) -> list[str]:
    warnings = []
    # Ligatures: common Unicode ligature characters
    ligature_count = len(re.findall(r'[ﬁﬂﬀﬃﬄﬅﬆ]', text))
    warnings.append(f"detected_ligatures: {ligature_count}")
    # Line hyphenation: word- at end of line
    hyphenation_count = len(re.findall(r'\w-\n\w', text))
    warnings.append(f"line_hyphenation_present: {hyphenation_count}")
    return warnings


def extract_pdf_to_json(pdf_path: str | Path) -> dict:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got: {pdf_path.suffix}")

    pages = []
    all_text = []

    with fitz.open(pdf_path) as doc:
        if len(doc) > MAX_PAGES:
            raise ValueError(f"PDF exceeds page limit ({len(doc)} pages, max {MAX_PAGES})")
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            pages.append({"page": page_num, "text": text})
            all_text.append(text)

    combined_text = "\n".join(all_text)
    if len(combined_text) > MAX_CHARS:
        raise ValueError(f"PDF exceeds character limit ({len(combined_text)} chars, max {MAX_CHARS})")
    warnings = detect_warnings(combined_text)

    return {
        "source": {
            "filename": Path(pdf_path).name,
            "type": "pdf",
            "sha256": compute_sha256(pdf_path),
            "page_count": len(pages),
        },
        "pages": pages,
        "warnings": warnings,
    }


def resolve_output_path(input_path: Path) -> Path:
    spec_folder = input_path.relative_to(INPUT_DIR).parent
    output_dir = OUTPUT_DIR / spec_folder
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / input_path.with_suffix(".json").name


def save_result(input_path: Path) -> Path:
    result = extract_pdf_to_json(input_path)
    jsonschema.validate(instance=result, schema=load_schema())
    output_path = resolve_output_path(input_path)
    with open(output_path, "w", encoding="utf-8") as f:
        # python dict/list -> json
        json.dump(result, f, indent=2, ensure_ascii=False)
    return output_path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if len(sys.argv) < 2:
        logging.error("Usage: python S0_extractor.py <path_to_pdf>")
        sys.exit(1)

    try:
        output_path = save_result(Path(sys.argv[1]))
        logging.info(f"Saved to {output_path}")
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        sys.exit(1)


if __name__ == "__main__":
    main()