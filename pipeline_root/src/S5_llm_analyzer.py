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
