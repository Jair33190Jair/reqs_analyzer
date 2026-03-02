# TODO: Not yet implemented — planned for v1
# Stage 2 — Preflight (cost protection gate)
#
# Responsibilities:
#   - Detect and count requirement IDs matching SYS-[A-Z]{2,8}-\d{3}
#   - Check for duplicates and numeric gaps
#   - Detect "shall" usage and section headings
#   - Compute a quality score and decide whether to proceed to LLM
#
# Input:  02_normalized_text.json
# Output: 03_after_preflight.json
#
# Gate policy: LLM is called only if score >= 0.80 and >= 5 requirements detected.
# See architecture/plan_v1.md §6 for full spec.
