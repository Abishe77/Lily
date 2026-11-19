import subprocess
import json

IMAGE_PATH = r"D:\Lily med\test2_notes.jpg"

PROMPT = r"""
Analyze this image as a document-content extraction task.

This image comes from a PDF, PowerPoint, or document uploaded to an AI study assistant.
The goal is to recover useful information that a normal text extractor may miss.

Extract ONLY information that is visibly present in the image.

You may analyze:
- diagrams and figures
- flowcharts
- arrows and relationships
- charts and graphs
- tables
- labeled illustrations
- screenshots
- equations and formulas
- text that is embedded inside images
- captions and labels
- visual relationships between elements

Do NOT analyze handwriting style or visual aesthetics.

Do NOT invent information.
Do NOT guess unclear text.
If text is unreadable, say "unreadable".
If a visual feature is absent, say "not observed".

Return ONLY valid JSON using this structure:

{
  "image_type": "",
  "visible_text": [],
  "visual_content": {
    "description": "",
    "elements": [],
    "relationships": []
  },
  "diagrams": [
    {
      "description": "",
      "labels": [],
      "connections": []
    }
  ],
  "charts_or_graphs": [
    {
      "type": "",
      "title": "",
      "axes": [],
      "visible_values": [],
      "main_observation": ""
    }
  ],
  "tables": [
    {
      "headers": [],
      "rows": []
    }
  ],
  "equations_or_formulas": [],
  "important_visual_information": [],
  "extraction_notes": []
}

Rules:
1. Only report information that can actually be seen.
2. Preserve visible labels and terminology as accurately as possible.
3. Describe arrows and connections explicitly when visible.
4. For diagrams, explain what the components are and how they are connected.
5. For charts, report only visible values or trends.
6. For tables, preserve visible rows and columns when readable.
7. Do not use outside knowledge to complete missing information.
8. Do not explain the academic topic beyond what the image itself shows.
9. If there is no content of a particular type, return an empty array.
10. Keep the output concise but information-dense.

"""

command = [
    "llama",
    "cli",
    "-hf",
    "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M",

    "--mmproj-device",
    "none",

    "--single-turn",

    "--image",
    IMAGE_PATH,

    "--prompt",
    PROMPT,

    "--no-display-prompt",
]

print("Starting Qwen Vision...")
print(f"Image: {IMAGE_PATH}")
print()

result = subprocess.run(
    command,
    capture_output=True,
    text=True,
)

print("===== QWEN OUTPUT =====")
print(result.stdout)

if result.stderr:
    print("\n===== QWEN LOG =====")
    print(result.stderr)

print("\nExit code:", result.returncode)