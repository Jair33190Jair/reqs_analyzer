# See: ../../architecture/architecture_v1.md
# TODO: Not yet implemented — planned for v1
# Stage 5 — Renderer
#
# Responsibilities:
#   - Transform 04_llm_analyzed.json into a human-readable HTML report
#   - Sections: metadata, metrics dashboard, requirements table, issues by severity, evidence appendix
#   - Use deterministic templating (e.g., Jinja2) — no AI calls during rendering
#   - Optional: export to PDF
#
# Input:  04_llm_analyzed.json
# Output: 05_report.html  [05_report.pdf optional]
#
# See architecture/plan_v1.md §9 for full spec.
