import os
import json
import anthropic
from dotenv import load_dotenv
# TODO: WIP — import path is wrong, replace with correct relative import once S3 is wired into the pipeline
from projects.embedded.reqs_analyzer.src.extractor import extract_text_from_pdf
# cheap_prompt is a simplified prompt designed to reduce token usage and cost,
from cheap_prompt import build_analysis_prompt, SYSTEM_PROMPT

load_dotenv()

def analyze_requirements_doc(pdf_path: str, output_path: str = "analysis_output.json"):
    # 1. Extract text
    print(f"Extracting text from: {pdf_path}")
    document_text = extract_text_from_pdf(pdf_path)
    
    if not document_text.strip():
        raise ValueError("No text extracted from PDF. It may be scanned/image-based.")
    
    print(f"Extracted {len(document_text)} characters across document.")
    
    # 2. Call Claude API
    print("Sending to Claude for analysis...")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    message = client.messages.create(
        model="claude-haiku-4-5",       # Use Haiku 4.5 cheaper model for cost ecciciency. Good enough for structured extraction.
        max_tokens=1, # Max tokens 8096 ~ 5 cents with haiku 4-5
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_analysis_prompt(document_text)}
        ]
    )
    
    raw_response = message.content[0].text
    """
    # 3. Parse JSON
    print("Parsing response...")
    try:
        analysis = json.loads(raw_response)
    except json.JSONDecodeError as e:
        # Save raw response for debugging
        with open("raw_response_debug.txt", "w") as f:
            f.write(raw_response)
        raise ValueError(f"Claude returned invalid JSON. Raw response saved to raw_response_debug.txt. Error: {e}")
    
    # 4. Add metadata
    analysis["metadata"] = {
        "source_file": pdf_path,
        "model_used": message.model,
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
    }
    
    # 5. Save output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Analysis complete. Output saved to: {output_path}")
    print(f"   Requirements found: {analysis['statistics']['total_requirements']}")
    print(f"   Flags raised: {analysis['statistics']['flagged_requirements']}")
    """
    print(raw_response)
    
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python analyzer.py <path_to_pdf> [output.json]")
        sys.exit(1)
    
    pdf = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "analysis_output.json"
    analyze_requirements_doc(pdf, out)