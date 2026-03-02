# 00_extractor.py — Test Plan

**Run from:** `pipeline_root/`
**Command:** `python src/00_extractor.py <path>`

---

## Happy Path

| #  | Input                                    | Expected                                                                                                 | Result |
| -- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------ |
| 00 | `input/arvms_spec/arvms_spec.pdf`      | `INFO: Saved to output/arvms_spec/machine/arvms_spec.json` — warnings: ligatures + hyphenation        | Pass   |
| 01 | `input/<project>/arvms_spec_clean.pdf` | `INFO: Saved to output/<project>/machine/clean_spec.json` — warnings: ligatures = 0, hyphenation = 0 | Pass   |

---

## Boundary

| # | Input       | Expected                                                       | Result |
| - | ----------- | -------------------------------------------------------------- | ------ |
| 3 | 10-page PDF | Pass — within limit                                           | Pass   |
| 4 | 11-page PDF | `ERROR: PDF exceeds page limit (11 pages, max 10)` — exit 1 | Pass   |

---

## Exception Cases

| # | Input                               | Expected                                                                  | Result |
| - | ----------------------------------- | ------------------------------------------------------------------------- | ------ |
| 5 | `input/spec/nonexistent.pdf`      | `ERROR: PDF not found: input/spec/nonexistent.pdf` — exit 1            | Pass   |
| 6 | `input/spec/file.txt`             | `ERROR: Expected a .pdf file, got: .txt` — exit 1                      | Pass   |
| 7 | PDF with >30,000 chars              | `ERROR: PDF exceeds character limit (XXXXX chars, max 30000)` — exit 1 | Pass   |
| 8 | `specs/arvms_spec/arvms_spec.pdf` | `ValueError` from `relative_to("input")` — exit 1                    | Pass   |

---

## Warning Coverage

| # | Input                                | Expected         | Result |
| - | ------------------------------------ | ---------------- | ------ |
| 9 | PDF with no ligatures or hyphenation | `warnings: []` | Pass   |
