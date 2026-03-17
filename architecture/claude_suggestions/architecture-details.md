# Structure Interpretation: Implementation Details

---

## Q1: What should Haiku's structure output look like?

### The input you send to Haiku

You don't send raw text. You send **annotated text** — the text plus whatever metadata PyMuPDF gives you. This is critical because without font metadata, Haiku is guessing. With it, Haiku is interpreting.

```python
# What PyMuPDF gives you per text block:
import fitz

doc = fitz.open("spec.pdf")
for page_num, page in enumerate(doc):
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        if block["type"] == 0:  # text block
            for line in block["lines"]:
                for span in line["spans"]:
                    # span contains:
                    #   "text": "3.2 Authentication Requirements"
                    #   "size": 14.0
                    #   "font": "Arial-Bold"
                    #   "flags": 20  (bit flags: bold=16, italic=2, etc.)
                    #   "bbox": (72.0, 145.2, 380.5, 162.1)  (position on page)
                    #   "color": 0  (RGB as int)
```

### What you actually send to Haiku

Transform the raw PyMuPDF output into a compact annotated format:

```
PAGE 1
───────
[H:14.0:B] 3. System Requirements
[P:11.0:R] This section describes the functional and non-functional requirements.
[H:12.0:B] 3.1 User Management
[P:11.0:R] The system shall allow administrators to create user accounts.
[P:11.0:R] The system shall enforce password policies as defined in section 5.2.
[P:9.0:I] Note: Password requirements are subject to corporate policy updates.
[TABLE_REGION: rows=5, cols=3, bbox=(72,400,540,520)]
| Role | Permission Level | Max Sessions |
| Admin | Full | Unlimited |
| User | Standard | 3 |
| Guest | Read-only | 1 |
| Auditor | Read + Export | 2 |
[H:12.0:B] 3.2 Authentication
[P:11.0:R] The system shall support single sign-on (SSO) via SAML 2.0.
[P:11.0:R] The system shall support multi-factor authentication for admin accounts.
[P:11.0:R] The authentication mechanism should comply with NIST 800-63B guidelines.
[P:11.0:R] TBD: Decision pending on whether biometric auth is in scope.
```

Key for annotations:
- `[H:14.0:B]` = Heading candidate, 14pt, Bold
- `[P:11.0:R]` = Paragraph text, 11pt, Regular
- `[P:9.0:I]` = Paragraph text, 9pt, Italic (likely a note)
- `[TABLE_REGION]` = Detected table area (see Q2 below)

### The prompt you send to Haiku

```
You are a requirements document structure parser. Given annotated text 
extracted from a PDF, identify the document structure.

ANNOTATED TEXT:
{annotated_text}

For each element, classify it as one of:
- SECTION_HEADING (with hierarchy level)
- REQUIREMENT (a "shall/must/should" statement or equivalent)
- EXPLANATORY_TEXT (context, description, rationale)
- NOTE (supplementary information, caveats)
- TABLE (structured data)
- FIGURE_REFERENCE (reference to a diagram/figure)
- TBD_PLACEHOLDER (unresolved item)
- CROSS_REFERENCE (pointer to another section/document)
- DEFINITION (term definition)
- CONSTRAINT (design/implementation constraint)

Respond ONLY with JSON. No preamble, no markdown fences.

Expected output format:
{
  "page": 1,
  "elements": [
    {
      "type": "SECTION_HEADING",
      "level": 1,
      "text": "3. System Requirements",
      "line_index": 0
    },
    {
      "type": "EXPLANATORY_TEXT",
      "text": "This section describes the functional and non-functional requirements.",
      "parent_section": "3. System Requirements",
      "line_index": 1
    },
    {
      "type": "SECTION_HEADING",
      "level": 2,
      "text": "3.1 User Management",
      "line_index": 2
    },
    {
      "type": "REQUIREMENT",
      "text": "The system shall allow administrators to create user accounts.",
      "parent_section": "3.1 User Management",
      "req_strength": "SHALL",
      "line_index": 3
    },
    {
      "type": "CROSS_REFERENCE",
      "text": "The system shall enforce password policies as defined in section 5.2.",
      "parent_section": "3.1 User Management",
      "req_strength": "SHALL",
      "references": ["5.2"],
      "line_index": 4
    },
    {
      "type": "NOTE",
      "text": "Note: Password requirements are subject to corporate policy updates.",
      "parent_section": "3.1 User Management",
      "line_index": 5
    },
    {
      "type": "TABLE",
      "caption": "Role-based access permissions",
      "headers": ["Role", "Permission Level", "Max Sessions"],
      "rows": [
        ["Admin", "Full", "Unlimited"],
        ["User", "Standard", "3"],
        ["Guest", "Read-only", "1"],
        ["Auditor", "Read + Export", "2"]
      ],
      "parent_section": "3.1 User Management",
      "line_index": 6
    },
    {
      "type": "REQUIREMENT",
      "text": "The system shall support single sign-on (SSO) via SAML 2.0.",
      "parent_section": "3.2 Authentication",
      "req_strength": "SHALL",
      "line_index": 8
    },
    {
      "type": "REQUIREMENT",
      "text": "The authentication mechanism should comply with NIST 800-63B guidelines.",
      "parent_section": "3.2 Authentication",
      "req_strength": "SHOULD",
      "line_index": 10
    },
    {
      "type": "TBD_PLACEHOLDER",
      "text": "TBD: Decision pending on whether biometric auth is in scope.",
      "parent_section": "3.2 Authentication",
      "line_index": 11
    }
  ]
}
```

### The Pydantic models for validation

```python
from pydantic import BaseModel, field_validator
from enum import Enum
from typing import Optional

class ElementType(str, Enum):
    SECTION_HEADING = "SECTION_HEADING"
    REQUIREMENT = "REQUIREMENT"
    EXPLANATORY_TEXT = "EXPLANATORY_TEXT"
    NOTE = "NOTE"
    TABLE = "TABLE"
    FIGURE_REFERENCE = "FIGURE_REFERENCE"
    TBD_PLACEHOLDER = "TBD_PLACEHOLDER"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    DEFINITION = "DEFINITION"
    CONSTRAINT = "CONSTRAINT"

class ReqStrength(str, Enum):
    SHALL = "SHALL"       # mandatory
    SHOULD = "SHOULD"     # recommended
    MAY = "MAY"           # optional
    WILL = "WILL"         # statement of fact / future intent
    MUST = "MUST"         # mandatory (often used interchangeably with SHALL)

class StructureElement(BaseModel):
    type: ElementType
    text: str
    line_index: int
    level: Optional[int] = None                # for headings
    parent_section: Optional[str] = None
    req_strength: Optional[ReqStrength] = None  # for requirements
    references: Optional[list[str]] = None      # for cross-references
    headers: Optional[list[str]] = None         # for tables
    rows: Optional[list[list[str]]] = None      # for tables
    caption: Optional[str] = None               # for tables

class PageStructure(BaseModel):
    page: int
    elements: list[StructureElement]

class DocumentStructure(BaseModel):
    pages: list[PageStructure]
```

---

## Validating AI output against source text

This is the part most people skip, and it's where silent data corruption enters your system.

### What can go wrong

1. **Hallucinated text.** Haiku rephrases "The system shall support SSO" as 
   "The system must implement SSO capabilities." Close, but not what the document says.
   Now your database has text that doesn't exist in the source.

2. **Missed elements.** Haiku skips a requirement because it looked like explanatory text.
   You never know it's missing.

3. **Invented structure.** Haiku decides something is a heading when it's actually a bold 
   requirement. Your hierarchy is now wrong.

4. **Merged elements.** Two separate requirements get combined into one.

5. **Duplicated elements.** The same requirement appears twice in the output.

### Validation strategy: Three layers

```
Layer 1: Schema validation        → Does the output match the Pydantic model?
Layer 2: Text fidelity check      → Does every text field exist in the source?
Layer 3: Coverage check            → Is all source text accounted for?
```

### Layer 1: Schema Validation (Pydantic handles this)

```python
import json

def parse_haiku_response(raw_response: str) -> PageStructure:
    """Parse and validate Haiku's JSON output."""
    try:
        # Strip markdown fences if present (LLMs sometimes add them despite instructions)
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        
        data = json.loads(cleaned)
        return PageStructure.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        # Log the failure, flag for manual review or retry
        raise StructureParsingError(f"Haiku output validation failed: {e}")
```

### Layer 2: Text Fidelity Check (THIS IS THE CRITICAL ONE)

```python
from difflib import SequenceMatcher

def validate_text_fidelity(
    elements: list[StructureElement],
    source_lines: list[str],  # the original annotated text, stripped of annotations
    similarity_threshold: float = 0.85
) -> list[FidelityIssue]:
    """
    Verify that every text field in the AI output actually exists in the source.
    Uses fuzzy matching because minor whitespace/punctuation differences are normal.
    """
    issues = []
    
    for element in elements:
        if element.type == ElementType.TABLE:
            # Tables validated separately (see below)
            continue
        
        ai_text = element.text.strip()
        
        # First: try exact substring match (fast path)
        source_joined = " ".join(source_lines)
        if ai_text in source_joined:
            continue
        
        # Second: try fuzzy match against individual source lines
        best_match_ratio = 0.0
        best_match_line = ""
        
        for source_line in source_lines:
            ratio = SequenceMatcher(None, ai_text.lower(), source_line.lower()).ratio()
            if ratio > best_match_ratio:
                best_match_ratio = ratio
                best_match_line = source_line
        
        if best_match_ratio < similarity_threshold:
            issues.append(FidelityIssue(
                element=element,
                issue_type="TEXT_NOT_IN_SOURCE",
                ai_text=ai_text,
                closest_source=best_match_line,
                similarity=best_match_ratio,
                severity="HIGH"  # The AI may have hallucinated this text
            ))
        elif best_match_ratio < 0.95:
            # Text is close but not exact — AI may have rephrased
            issues.append(FidelityIssue(
                element=element,
                issue_type="TEXT_MODIFIED",
                ai_text=ai_text,
                closest_source=best_match_line,
                similarity=best_match_ratio,
                severity="LOW"  # Minor rephrasing, but flag it
            ))
            # AUTO-FIX: Replace AI text with source text
            element.text = best_match_line
    
    return issues
```

### Layer 3: Coverage Check

```python
def validate_coverage(
    elements: list[StructureElement],
    source_lines: list[str],
    min_coverage: float = 0.90  # at least 90% of source lines should be accounted for
) -> CoverageReport:
    """
    Check that the AI didn't silently skip content.
    Every substantive source line should map to at least one element.
    """
    matched_source_lines = set()
    
    for element in elements:
        for i, source_line in enumerate(source_lines):
            if SequenceMatcher(None, element.text.lower(), source_line.lower()).ratio() > 0.80:
                matched_source_lines.add(i)
    
    unmatched = []
    for i, line in enumerate(source_lines):
        if i not in matched_source_lines:
            stripped = line.strip()
            # Ignore blank lines and very short lines (page numbers, etc.)
            if len(stripped) > 10:
                unmatched.append({"line_index": i, "text": stripped})
    
    coverage = len(matched_source_lines) / max(len(source_lines), 1)
    
    return CoverageReport(
        total_source_lines=len(source_lines),
        matched_lines=len(matched_source_lines),
        coverage_ratio=coverage,
        unmatched_lines=unmatched,
        passed=coverage >= min_coverage
    )
```

### When validation fails: what to do

| Failure | Action |
|---|---|
| Schema validation fails | Retry the Haiku call (up to 2 retries). If still fails, flag document for manual review. |
| Text fidelity < 0.85 | Replace AI text with closest source text automatically. If no close match exists, flag the element as "unverified." |
| Coverage < 90% | Re-run Haiku on the missed sections specifically. If still missed, add unmatched lines as "UNCLASSIFIED" elements. |
| Consistent failures on a document | This document likely has unusual formatting. Fall back to Strategy C (send full PDF via vision) or flag for manual structuring. |

### The validation pipeline as code

```python
def process_page(page_num: int, page: fitz.Page) -> ValidatedPageStructure:
    # Step 1: Extract annotated text
    annotated_text, source_lines = extract_annotated_text(page)
    
    # Step 2: Send to Haiku for structure interpretation
    raw_response = call_haiku(annotated_text, STRUCTURE_PROMPT)
    
    # Step 3: Schema validation
    page_structure = parse_haiku_response(raw_response)  # raises on failure
    
    # Step 4: Text fidelity check
    fidelity_issues = validate_text_fidelity(page_structure.elements, source_lines)
    high_severity = [i for i in fidelity_issues if i.severity == "HIGH"]
    
    if len(high_severity) > 3:
        # Too many hallucinations — retry with stricter prompt
        raw_response = call_haiku(annotated_text, STRICT_STRUCTURE_PROMPT)
        page_structure = parse_haiku_response(raw_response)
        fidelity_issues = validate_text_fidelity(page_structure.elements, source_lines)
    
    # Step 5: Coverage check
    coverage = validate_coverage(page_structure.elements, source_lines)
    
    if not coverage.passed:
        # Add unmatched lines as UNCLASSIFIED
        for unmatched in coverage.unmatched_lines:
            page_structure.elements.append(StructureElement(
                type=ElementType.EXPLANATORY_TEXT,  # safe default
                text=unmatched["text"],
                line_index=unmatched["line_index"],
                _unclassified=True  # flag for later review
            ))
    
    return ValidatedPageStructure(
        page=page_structure,
        fidelity_issues=fidelity_issues,
        coverage=coverage,
        confidence=calculate_confidence(fidelity_issues, coverage)
    )
```

---

## Q2: Will AI identify tables from extracted text alone?

### Short answer: Poorly, if you send raw text. Reasonably well, if you pre-detect table regions.

### The problem

When PyMuPDF extracts text from a table, it gives you something like this:

```
Role Permission Level Max Sessions
Admin Full Unlimited
User Standard 3
Guest Read-only 1
```

Is that a table? Or four lines of text that happen to be about roles? Without spatial information, even a human might not be sure. The AI has even less to go on.

Worse, complex tables produce garbled text:

```
Role Permission Max    Admin Full Unlimited
Level Sessions
User Standard 3       Guest Read-only 1
```

PyMuPDF reads text blocks left-to-right, top-to-bottom. If table cells have variable heights or merged cells, the extraction order is unpredictable.

### The solution: Pre-detect tables with pdfplumber, then annotate

```python
import pdfplumber

def extract_with_table_awareness(pdf_path: str) -> list[AnnotatedPage]:
    """
    Use pdfplumber to detect table regions, 
    then use PyMuPDF for text outside tables.
    """
    plumber_pdf = pdfplumber.open(pdf_path)
    fitz_doc = fitz.open(pdf_path)
    
    pages = []
    
    for page_num in range(len(fitz_doc)):
        plumber_page = plumber_pdf.pages[page_num]
        fitz_page = fitz_doc[page_num]
        
        # Step 1: Detect tables with pdfplumber
        tables = plumber_page.find_tables()
        table_regions = []
        
        for table in tables:
            bbox = table.bbox  # (x0, y0, x1, y1)
            extracted_table = table.extract()  # list of lists
            
            # Clean up None values and whitespace
            cleaned = []
            for row in extracted_table:
                cleaned.append([cell.strip() if cell else "" for cell in row])
            
            table_regions.append({
                "bbox": bbox,
                "headers": cleaned[0] if cleaned else [],
                "rows": cleaned[1:] if len(cleaned) > 1 else [],
                "raw": cleaned
            })
        
        # Step 2: Extract non-table text with PyMuPDF
        # Exclude regions occupied by tables
        text_blocks = []
        for block in fitz_page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            
            block_bbox = block["bbox"]
            
            # Check if this text block overlaps with any table region
            is_in_table = False
            for table_region in table_regions:
                if bboxes_overlap(block_bbox, table_region["bbox"]):
                    is_in_table = True
                    break
            
            if not is_in_table:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text_blocks.append({
                            "text": span["text"],
                            "font_size": span["size"],
                            "font_name": span["font"],
                            "bold": bool(span["flags"] & 16),
                            "italic": bool(span["flags"] & 2),
                            "bbox": span["bbox"]
                        })
        
        pages.append(AnnotatedPage(
            page_num=page_num,
            text_blocks=text_blocks,
            tables=table_regions
        ))
    
    return pages
```

### What you send to Haiku (with pre-detected tables)

```
PAGE 3
───────
[H:14.0:B] 3.1 User Management
[P:11.0:R] The system shall allow administrators to create user accounts.
[P:11.0:R] The following roles are defined:
[TABLE: 5 rows × 3 cols]
| Role | Permission Level | Max Sessions |
|------|-----------------|--------------|
| Admin | Full | Unlimited |
| User | Standard | 3 |
| Guest | Read-only | 1 |
| Auditor | Read + Export | 2 |
[P:11.0:R] Each role shall have configurable timeout periods.
```

Now Haiku sees a clean table and can identify what it represents (a reference table of role definitions) without having to guess whether garbled text was originally tabular.

### Summary of responsibilities

```
pdfplumber:  "Here is a table at position (72, 400, 540, 520) with these cells."
             → Structural detection (IS this a table? What are its boundaries?)

Haiku:       "This table defines user roles and their permissions. 
              It supports requirements in section 3.1."
             → Semantic interpretation (WHAT does this table mean?)
```

Do not ask the AI to detect whether something is a table from raw text. That's a spatial/structural task that pdfplumber handles deterministically. DO ask the AI what the table means, whether it contains requirements, and how it relates to surrounding text.

---

## Q3: Generate hierarchy with LLM or Python?

### Answer: Python builds the tree. LLM provides the raw classification. Neither does the other's job well.

### What the LLM is good at (and should do)

The LLM looks at annotated text and says:

```json
{"type": "SECTION_HEADING", "level": 1, "text": "3. System Requirements", "line_index": 0}
{"type": "SECTION_HEADING", "level": 2, "text": "3.1 User Management", "line_index": 2}
{"type": "REQUIREMENT", "text": "The system shall...", "parent_section": "3.1 User Management", "line_index": 3}
```

This is a flat list of classified elements with level hints. The LLM is identifying WHAT each element is and roughly WHERE it sits in the hierarchy.

### What the LLM is bad at (and should NOT do)

Producing a correctly nested tree structure. Here's why:

```json
// Asking the LLM to produce nested output leads to:
{
  "section": "3. System Requirements",
  "children": [
    {
      "section": "3.1 User Management",
      "children": [
        {"req": "The system shall allow..."},
        {"req": "The system shall enforce..."},
        // LLM forgets a requirement here because nested JSON is hard to track
        {
          "section": "3.1.1 Role Definitions",
          // LLM invents this subsection — it doesn't exist in the document
          "children": [...]
        }
      ]
    }
  ]
}
```

Problems with LLM-generated trees:
1. LLMs lose track of nesting depth in long documents
2. They silently drop elements that don't fit their mental model
3. They invent intermediate nodes to make the tree "make sense"
4. JSON nesting errors compound (one wrong bracket breaks everything downstream)
5. You can't validate the tree structure against source line-by-line

### What Python is good at (and should do)

Taking the flat classified list and building a correct tree with deterministic rules:

```python
def build_hierarchy(elements: list[StructureElement]) -> DocumentTree:
    """
    Build a hierarchical tree from a flat list of classified elements.
    The LLM classified each element. Python enforces the tree structure.
    """
    root = SectionNode(
        section_id="root",
        title="Document Root",
        level=0,
        children=[],
        requirements=[]
    )
    
    # Stack tracks the current path in the tree
    # Each entry is (level, node)
    stack: list[tuple[int, SectionNode]] = [(0, root)]
    
    for element in elements:
        if element.type == ElementType.SECTION_HEADING:
            new_section = SectionNode(
                section_id=generate_section_id(element.text),
                title=element.text,
                level=element.level,
                children=[],
                requirements=[]
            )
            
            # Pop stack until we find the parent level
            while stack and stack[-1][0] >= element.level:
                stack.pop()
            
            # Attach to current parent
            parent = stack[-1][1] if stack else root
            parent.children.append(new_section)
            stack.append((element.level, new_section))
        
        elif element.type == ElementType.REQUIREMENT:
            # Attach to the most recent section
            current_section = stack[-1][1] if stack else root
            current_section.requirements.append(RequirementNode(
                text=element.text,
                strength=element.req_strength,
                line_index=element.line_index
            ))
        
        elif element.type == ElementType.TABLE:
            current_section = stack[-1][1] if stack else root
            current_section.tables.append(TableNode(
                headers=element.headers,
                rows=element.rows,
                caption=element.caption,
                line_index=element.line_index
            ))
        
        else:
            # Notes, explanatory text, etc. — attach to current section
            current_section = stack[-1][1] if stack else root
            current_section.other_content.append(element)
    
    return DocumentTree(root=root)
```

### Why this split works

| Task | Who | Why |
|---|---|---|
| "Is this a heading?" | LLM | Requires understanding context, font cues, document conventions |
| "What level is this heading?" | LLM (with Python validation) | LLM reads "3.1.2" and says level 3. Python validates that level 3 follows level 2. |
| "Is this a requirement?" | LLM | Requires understanding language ("shall", "must", imperative mood) |
| "Building the tree from levels" | Python | Deterministic stack-based algorithm. No AI needed. No hallucination risk. |
| "Assigning parent-child relationships" | Python | Based on level numbers. Mechanical. |
| "Generating section IDs" | Python | Based on heading text and position. Deterministic. |
| "Generating requirement IDs" | Python | Based on parent section ID + sequence number. Deterministic. |

### Python-side validation of LLM level assignments

The LLM might say something is "level 3" when it should be "level 2." Add sanity checks:

```python
def validate_heading_levels(elements: list[StructureElement]) -> list[StructureElement]:
    """
    Fix common LLM mistakes in heading level assignment.
    """
    headings = [e for e in elements if e.type == ElementType.SECTION_HEADING]
    
    for i, heading in enumerate(headings):
        # Rule 1: Numbered headings have implicit levels
        # "3" = level 1, "3.1" = level 2, "3.1.2" = level 3
        number_match = re.match(r'^(\d+(?:\.\d+)*)', heading.text)
        if number_match:
            dots = number_match.group(1).count('.')
            implicit_level = dots + 1
            if heading.level != implicit_level:
                heading.level = implicit_level  # trust the numbering over the LLM
        
        # Rule 2: No level jumps > 1
        # Can't go from level 1 directly to level 3
        if i > 0:
            prev_level = headings[i-1].level
            if heading.level > prev_level + 1:
                heading.level = prev_level + 1  # clamp to valid jump
    
    return elements
```

### The complete flow

```
PDF
 │
 ▼
PyMuPDF (text + font metadata) ──────────────────────────── deterministic
pdfplumber (table detection)   ──────────────────────────── deterministic
 │
 ▼
Annotated text with tables
 │
 ▼
Claude Haiku (classify each element) ───────────────────── AI judgment
 │
 ▼
Flat list: [{type, text, level, line_index}, ...]
 │
 ▼
Text fidelity validation ───────────────────────────────── deterministic
Coverage validation ────────────────────────────────────── deterministic
Level sanity check  ────────────────────────────────────── deterministic
 │
 ▼
Python tree builder (stack algorithm) ──────────────────── deterministic
 │
 ▼
ID generator (section IDs + requirement IDs) ───────────── deterministic
 │
 ▼
Hierarchical document structure with IDs
 │
 ▼
PostgreSQL storage
```

The rule of thumb: **AI decides WHAT things are. Python decides WHERE they go.**

AI is good at fuzzy classification. Python is good at structural correctness. 
Don't ask AI to do Python's job (building trees), and don't ask Python to do 
AI's job (interpreting whether "Note:" is a heading or a note).
