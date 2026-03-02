#!/bin/bash
# Convert all .md files under arvms_specs to PDF using pandoc.
# Output PDF is placed next to the source .md file.

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

find "$BASE_DIR" -name "*.md" | while read -r md_file; do
    pdf_file="${md_file%.md}.pdf"
    if [ -f "$pdf_file" ]; then
        echo "Skipping (PDF exists): $md_file"
        continue
    fi
    echo "Converting: $md_file -> $pdf_file"
    pandoc "$md_file" -o "$pdf_file" && echo "  OK" || echo "  FAILED"
done
