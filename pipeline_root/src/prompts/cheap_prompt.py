SYSTEM_PROMPT = """You are a senior embedded SW/systems architect expert in ISO 26262, ASPICE, and real-time systems. Review requirements documents as a domain expert accountable for safety and correctness."""

def build_analysis_prompt(document_text: str) -> str:
    return f"""Review this embedded SW requirements doc. Return ONLY valid JSON (no markdown, no preamble) with this structure:

{{
  "document": {{id, status, type, title, description, owners}},
  "chapters": [{{id, parent_chapter_id, status, type, title, description}}],
  "requirements": [{{id, chapter_id, status, title, description, type, owner}}],
  "informations": [{{id, chapter_id, status, title, description}}],
  "ai_analysis": {{
    "id", "source_id", "description",
    "flags": [{{id, source_id, flag_category, flag_type, severity, description, recommendation, apply_ai_suggestion:""}}],
    "statistics": {{total_requirements, total_flags, flags_by_category, flags_by_type, flags_by_severity}}
  }}
}}

RULES:
- Missing id → gen_<type>_<n>; missing title → "Gen: <generated>"; missing description → "Gen: <generated>"; missing status → "Not found"
- Generated chapters: status="gen-draft"; group reqs logically, minimize fragmentation
- flag_category: core|coherence|attributes|sufficiency
- flag_type: core→testability|robustness|appropriateness; coherence→consistency|redundancy|meaningfulness; attributes→id|asil_level|test_criteria|traceability; sufficiency→completeness|compactness
- severity: critical|major|minor
- req type: functional|non-functional|safety|interface|performance|derived

DOC:
---
{document_text}
---"""