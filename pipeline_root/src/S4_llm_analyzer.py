# See: ../../architecture/architecture_v1.md
# TODO: Not yet implemented — planned for v1
# Stage 5 — LLM Analyzer
#
# Responsibilities:
#   - Assess quality, completeness, safety, and verifiability of structured requirements
#   - Produce flags per requirement (severity: low / medium / high / critical)
#   - Categories: verifiability, ambiguity, consistency, completeness,
#                 feasibility, safety, security, performance, traceability, style
#   - Produce aggregate statistics
#
# Input:  03_llm_structured.json  (S3 artifact — loc-resolved, validated against 03_llm_structured.schema.v1.json)
# Output: 05_llm_analyzed.json   (schema: 05_llm_analyzed.schema.v1.json)
#
# See architecture/plan_v1.md §8 for full spec.

#!/usr/bin/env python3
"""
Requirement Quality Reviewer - Pass 3 (Individual Requirement Quality)
======================================================================
A simple, single-pass reviewer that checks each requirement against
ASPICE/ISO26262-aligned quality criteria.

Usage:
    python review_quality.py sample_input.json -o findings.json

Design decisions:
- Single API call with all requirements (for small specs <50 items)
- Structured JSON output with finding schema
- Deterministic preprocessing, LLM only for judgment
- Easy to debug: raw prompt and raw response are saved alongside findings
"""

import json
import sys
import argparse
import os
from datetime import datetime, timezone

import anthropic


# ---------------------------------------------------------------------------
# 1. PREPROCESSING - Strip input to only what the LLM needs
# ---------------------------------------------------------------------------

def preprocess_spec(raw: dict) -> dict:
    """
    Reduce the full spec JSON to the minimum the LLM needs for quality review.
    For this pass we need: item_id, classification, content, section context.
    We do NOT need: loc, source, hierarchical_number on items, page refs.
    """
    # Build a section lookup so we can give the LLM section context per item
    section_lookup = {}
    for sec in raw.get("sections", []):
        section_lookup[sec["internal_id"]] = {
            "number": sec["hierarchical_number"],
            "title": sec["title"]
        }

    # Slim down spec items
    items = []
    for item in raw.get("spec_items", []):
        # Derive parent section from internal_id (e.g., "G3.1-001" -> "G3.1")
        parent_key = item["internal_id"].rsplit("-", 1)[0] if "-" in item["internal_id"] else None
        section_ctx = section_lookup.get(parent_key, {})

        items.append({
            "item_id": item["item_id"],
            "classification": item["classification"],
            "section": section_ctx.get("title", "Unknown"),
            "section_number": section_ctx.get("number", ""),
            "content": item["content"].replace(item["item_id"] + "\n", "").strip()
        })

    return {"items": items, "total_count": len(items)}


# ---------------------------------------------------------------------------
# 2. PROMPT CONSTRUCTION
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert automotive systems and software architect performing a \
requirement quality review. You have deep expertise in ASPICE, ISO 26262, \
and IEEE 830 (now ISO/IEC/IEEE 29148) requirement quality criteria.

Your task: Review each requirement individually for QUALITY defects.

## Quality Criteria (check each requirement against ALL of these)

1. **AMBIGUITY** - Contains vague/subjective terms ("appropriate", "timely", \
"sufficient", "properly", "real-time" without a numeric bound, "etc.", \
"and/or", "as needed"). Would two engineers implement this identically?

2. **TESTABILITY** - Can a concrete pass/fail test be written from this \
requirement alone? Are thresholds, conditions, and expected behaviors \
explicit enough to verify?

3. **ATOMICITY** - Does the requirement contain exactly ONE "shall" \
statement? Multiple behaviors bundled in one requirement are a defect.

4. **OVERCONSTRAINT** - Does the requirement prescribe implementation \
(specific algorithms, specific HW components, internal architecture) when \
it should state the NEED instead? A system-level requirement should say \
WHAT, not HOW. Exception: if the constraint is genuinely necessary at \
system level (e.g., safety-critical timing).

5. **MISSING_CONTEXT** - Is the requirement missing boundary conditions, \
operating modes, failure behavior, or environmental conditions that would \
be needed for implementation? For example: a timing requirement without \
specifying under what conditions the timing applies.

6. **TERMINOLOGY** - Does it use inconsistent terms (referring to the same \
thing with different names across the spec) or undefined domain terms?

## Rules
- Only flag REAL issues. Do not flag something just to generate output.
- Severity CRITICAL = blocks downstream work or has safety implications.
- Severity MAJOR = will likely cause rework or ambiguous implementation.
- Severity MINOR = improvement opportunity, wording clarification.
- If a requirement has NO quality issues, do NOT include it in findings.
- Be specific in your description: quote the problematic word/phrase.
- Keep recommendations actionable and concrete.

## Output Format
Return ONLY a JSON array of finding objects. No markdown, no preamble.
Each finding object:
{
  "flag_id": "QA-NNN",          // sequential, starting at QA-001
  "affected_items_ids": "SYS-XXXX-NNN",      // the requirement being flagged 
  "affected_internal_ids": "SYS-XXXX-NNN",      // the requirement being flagged   
  "category": "AMBIGUITY|TESTABILITY|ATOMICITY|OVERCONSTRAINT|MISSING_CONTEXT|TERMINOLOGY",
  "severity": "CRITICAL|MAJOR|MINOR",
  "type": "FINDING|QUESTION",      // FINDING=defect, QUESTION=needs clarification
  "description": "...",            // what is wrong, quote specific words
  "recommendation": "..."         // concrete fix suggestion
  "status"
}

If there are zero findings, return an empty array: []
"""


def build_user_prompt(processed: dict) -> str:
    """Build the user message with the requirements to review."""
    lines = [<<<
        "Review the following requirements for quality issues.\n",
        f"Total requirements: {processed['total_count']}\n",
        "---\n"
    ]
    for item in processed["items"]:
        lines.append(
            f"[{item['item_id']}] (Section {item['section_number']} {item['section']}, "
            f"classification: {item['classification']})\n"
            f"{item['content']}\n"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. LLM CALL
# ---------------------------------------------------------------------------

def call_review(system_prompt: str, user_prompt: str, model: str = "claude-sonnet-4-20250514") -> str:
    """Make the API call and return raw response text."""
    client = anthropic.Anthropic()

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2  # Low temperature for consistent, factual output
    )

    return message.content[0].text


def mock_review_response() -> str:
    """Return a realistic mock response for dry-run/demo mode."""
    findings = [
        {
            "finding_id": "QA-001",
            "item_id": "SYS-FUNC-003",
            "category": "AMBIGUITY",
            "severity": "MAJOR",
            "type": "FINDING",
            "description": "\"real-time\" is used without a numeric bound. What is the maximum latency for obstacle avoidance? 10ms? 100ms? 500ms? Different interpretations lead to vastly different implementations.",
            "recommendation": "Replace \"in real-time\" with a concrete timing requirement, e.g., \"within 100 ms of sensor detection\" or reference a separate timing budget requirement."
        },
        {
            "finding_id": "QA-002",
            "item_id": "SYS-FUNC-004",
            "category": "ATOMICITY",
            "severity": "MINOR",
            "type": "FINDING",
            "description": "This requirement bundles two distinct behaviors: (1) detecting cliffs/stairs and (2) preventing falling. Detection and reaction should be separately verifiable.",
            "recommendation": "Split into two requirements: one for detection (with sensor type and detection distance) and one for the reaction (e.g., \"shall stop within X cm of a detected cliff edge\")."
        },
        {
            "finding_id": "QA-003",
            "item_id": "SYS-FUNC-002",
            "category": "MISSING_CONTEXT",
            "severity": "MAJOR",
            "type": "QUESTION",
            "description": "\"±5 cm accuracy\" - under what conditions? This accuracy may not be achievable during initial mapping, on featureless surfaces (long corridors), or after wheel slip. Is this a steady-state requirement or must it hold at all times?",
            "recommendation": "Add operating conditions: e.g., \"after initial mapping is complete, on surfaces with sufficient visual/geometric features, and at speeds below X m/s\"."
        },
        {
            "finding_id": "QA-004",
            "item_id": "SYS-SAFE-002",
            "category": "TESTABILITY",
            "severity": "CRITICAL",
            "type": "FINDING",
            "description": "\"limit brush torque to prevent injury\" - no torque value is specified, and \"prevent injury\" is not a testable criterion. What torque limit? What injury threshold (e.g., ISO 13482 personal care robot limits)?",
            "recommendation": "Specify a numeric torque limit (e.g., \"shall not exceed 0.5 Nm\") and reference the applicable safety standard for the injury threshold."
        },
        {
            "finding_id": "QA-005",
            "item_id": "SYS-FUNC-011",
            "category": "MISSING_CONTEXT",
            "severity": "MAJOR",
            "type": "QUESTION",
            "description": "\"adjust suction based on detected floor type\" - what floor types must be distinguished? Only carpet vs hard floor, or also tile vs wood vs vinyl? What suction level maps to which floor type?",
            "recommendation": "Define the set of detectable floor types and either specify the suction mapping or reference a separate configuration requirement."
        },
        {
            "finding_id": "QA-006",
            "item_id": "SYS-FUNC-030",
            "category": "MISSING_CONTEXT",
            "severity": "MAJOR",
            "type": "FINDING",
            "description": "\"when battery < 20%\" - does the system need enough charge to actually REACH the dock from its farthest possible position? 20% may be insufficient if the robot is far from the dock. No requirement addresses this.",
            "recommendation": "Consider replacing fixed 20% threshold with a dynamic threshold based on estimated distance to dock, or add a requirement that the system shall calculate if remaining charge is sufficient to reach the dock."
        },
        {
            "finding_id": "QA-007",
            "item_id": "SYS-FUNC-032",
            "category": "AMBIGUITY",
            "severity": "MINOR",
            "type": "FINDING",
            "description": "\"support automatic charging\" is redundant with SYS-FUNC-030 (auto return to dock) and SYS-FUNC-031 (resume after recharge). What does this add beyond those two? If it means the electrical charging process itself, say so explicitly.",
            "recommendation": "Clarify what \"automatic charging\" means that is not already covered by SYS-FUNC-030/031. Consider: \"The system shall initiate battery charging automatically upon docking without user intervention.\""
        },
        {
            "finding_id": "QA-008",
            "item_id": "SYS-SW-001",
            "category": "OVERCONSTRAINT",
            "severity": "MAJOR",
            "type": "FINDING",
            "description": "Prescribing a specific 3-layer architecture (Application / Middleware / HAL) at system requirement level constrains the software design team. This is a software architecture decision, not a system need.",
            "recommendation": "At system level, state the NEED: e.g., \"The software architecture shall support independent update of application logic without modifying hardware interfaces.\" Move the specific layering to the SW architecture document."
        },
        {
            "finding_id": "QA-009",
            "item_id": "SYS-HW-001",
            "category": "AMBIGUITY",
            "severity": "MAJOR",
            "type": "FINDING",
            "description": "\"LIDAR or vision-based\" leaves the fundamental sensor technology unresolved. These have very different performance characteristics, cost, power, and SW requirements. This is a system-level decision that should be made, not deferred in a requirement.",
            "recommendation": "Either select one technology and specify its key parameters (range, resolution, FoV) or split into two variant requirements with a decision gate. Do not leave a disjunction in a shall-statement."
        },
        {
            "finding_id": "QA-010",
            "item_id": "SYS-PERF-001",
            "category": "TESTABILITY",
            "severity": "MAJOR",
            "type": "QUESTION",
            "description": "\"Cleaning coverage efficiency >= 95%\" - how is this measured? What is the reference area? Does it include under-furniture areas the robot physically cannot reach? What about areas blocked by obstacles?",
            "recommendation": "Define the measurement method: e.g., \"of the accessible floor area (excluding areas under furniture with clearance < X cm), the system shall cover >= 95% in a single cleaning cycle, measured by [method].\""
        },
        {
            "finding_id": "QA-011",
            "item_id": "SYS-SAFE-010",
            "category": "TESTABILITY",
            "severity": "CRITICAL",
            "type": "FINDING",
            "description": "\"prevent battery overcharge and deep discharge\" - no voltage/current thresholds specified. What are the overcharge and deep discharge limits? These are safety-critical values that must be explicit.",
            "recommendation": "Specify: \"shall disconnect charging when cell voltage exceeds X.XX V\" and \"shall enter shutdown when cell voltage drops below X.XX V\". Reference the battery cell datasheet or IEC 62133."
        },
        {
            "finding_id": "QA-012",
            "item_id": "SYS-SAFE-011",
            "category": "TESTABILITY",
            "severity": "CRITICAL",
            "type": "FINDING",
            "description": "\"monitor motor temperature and prevent overheating\" - no temperature threshold, no monitoring rate, no specified reaction. What temperature is \"overheating\"? What happens when it's reached - reduce power? Stop? Alert?",
            "recommendation": "Specify: threshold temperature (e.g., \"winding temperature > 85°C\"), monitoring interval, and the required reaction (e.g., \"shall reduce motor power to 50%\" or \"shall stop motor within 500 ms\")."
        },
        {
            "finding_id": "QA-013",
            "item_id": "SYS-FUNC-031",
            "category": "MISSING_CONTEXT",
            "severity": "MINOR",
            "type": "QUESTION",
            "description": "\"resume cleaning after recharge\" - from where? Does it return to the exact position where it stopped, or restart the room? What if the environment changed during charging (moved furniture)?",
            "recommendation": "Specify resume behavior: \"shall return to the last cleaning position and continue the planned path\" or \"shall re-localize and continue from the nearest unfinished area.\""
        },
        {
            "finding_id": "QA-014",
            "item_id": "SYS-SEC-002",
            "category": "MISSING_CONTEXT",
            "severity": "MAJOR",
            "type": "FINDING",
            "description": "\"secure OTA firmware updates\" - \"secure\" is not defined. Does this mean signed packages? Encrypted transport? Rollback capability? All of these? Without specifics this is not implementable or testable.",
            "recommendation": "Decompose into specific security properties: integrity verification (signed images), confidentiality (encrypted transport - already partially covered by SYS-SEC-001), rollback protection, and atomic update (no bricking on power loss)."
        }
    ]
    return json.dumps(findings, indent=2)


# ---------------------------------------------------------------------------
# 4. POSTPROCESSING - Parse and wrap findings
# ---------------------------------------------------------------------------

def parse_findings(raw_response: str) -> list:
    """Parse the LLM response into structured findings."""
    # Strip any markdown fencing the model might add despite instructions
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]  # remove first line
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    findings = json.loads(text)

    # Validate and add disposition template to each finding
    for f in findings:
        f["pass"] = "QUALITY"
        f["disposition"] = {
            "status": "OPEN",
            "author_response": "",
            "resolved_in_version": None,
            "reviewed_by": None,
            "review_date": None
        }

    return findings


def build_review_report(findings: list, processed: dict, model: str) -> dict:
    """Wrap findings in a report envelope with metadata."""
    return {
        "review_metadata": {
            "pass": "QUALITY",
            "model": model,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_requirements_reviewed": processed["total_count"],
            "total_findings": len(findings),
            "severity_summary": {
                "CRITICAL": sum(1 for f in findings if f["severity"] == "CRITICAL"),
                "MAJOR": sum(1 for f in findings if f["severity"] == "MAJOR"),
                "MINOR": sum(1 for f in findings if f["severity"] == "MINOR"),
            }
        },
        "findings": findings
    }


# ---------------------------------------------------------------------------
# 5. MAIN
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Requirement Quality Reviewer")
    parser.add_argument("input_file", help="Path to spec JSON file")
    parser.add_argument("-o", "--output", default="findings_quality.json", help="Output findings file")
    parser.add_argument("-m", "--model", default="claude-sonnet-4-20250514", help="Model to use")
    parser.add_argument("--save-debug", action="store_true", help="Save prompt and raw response for debugging")
    parser.add_argument("--dry-run", action="store_true", help="Use mock response (no API key needed)")
    args = parser.parse_args()

    # Load and preprocess
    print(f"Loading spec from {args.input_file}...")
    with open(args.input_file) as f:
        raw = json.load(f)

    processed = preprocess_spec(raw)
    print(f"Preprocessed {processed['total_count']} requirements.")

    # Build prompts
    user_prompt = build_user_prompt(processed)

    if args.save_debug:
        debug_dir = os.path.dirname(args.output) or "."
        with open(os.path.join(debug_dir, "debug_system_prompt.txt"), "w") as f:
            f.write(SYSTEM_PROMPT)
        with open(os.path.join(debug_dir, "debug_user_prompt.txt"), "w") as f:
            f.write(user_prompt)
        print("Saved debug prompts.")

    # Call LLM
    if args.dry_run:
        print("DRY RUN - using mock response...")
        raw_response = mock_review_response()
    else:
        print(f"Calling {args.model}...")
        raw_response = call_review(SYSTEM_PROMPT, user_prompt, args.model)

    if args.save_debug:
        with open(os.path.join(debug_dir, "debug_raw_response.txt"), "w") as f:
            f.write(raw_response)
        print("Saved raw response.")

    # Parse and build report
    findings = parse_findings(raw_response)
    report = build_review_report(findings, processed, args.model)

    # Save
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print(f"REVIEW COMPLETE")
    print(f"{'='*60}")
    print(f"Requirements reviewed: {processed['total_count']}")
    print(f"Total findings:        {report['review_metadata']['total_findings']}")
    print(f"  CRITICAL:            {report['review_metadata']['severity_summary']['CRITICAL']}")
    print(f"  MAJOR:               {report['review_metadata']['severity_summary']['MAJOR']}")
    print(f"  MINOR:               {report['review_metadata']['severity_summary']['MINOR']}")
    print(f"\nFindings saved to: {args.output}")


if __name__ == "__main__":
    main()