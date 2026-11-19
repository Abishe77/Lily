import base64
import json
import os

from google import genai


MODEL = "gemini-3.8-flash"


EXPECTED_KEYS = {
    "image_type",
    "visible_text",
    "visual_content",
    "diagrams",
    "charts_or_graphs",
    "tables",
    "equations_or_formulas",
    "important_visual_information",
    "extraction_notes"
}


PROMPT = r"""
Read this image as a source document.

Your job is to extract everything that is visibly present in the image.

Do not summarize the image.

Do not explain the subject.

Do not correct the source.

Do not infer information that is not visible.

Read all visible text, including text inside diagrams, boxes, tables, charts, labels, arrows, and handwritten content.

Preserve mathematical notation as closely as possible to what is visibly shown.

If text is unclear, write "unreadable" instead of inventing it.

Return the complete source extraction using the required JSON structure.

Extraction requirements:

1. visible_text must contain all clearly readable text from the image.
2. Do not intentionally shorten or summarize visible_text.
3. Include text that appears inside visual elements.
4. equations_or_formulas must contain mathematical expressions that are visibly present.
5. diagrams must describe visible diagrams and preserve their labels and connections.
6. charts_or_graphs must preserve visible titles, labels, axes, legends, and values when present.
7. tables must preserve visible headers and rows when present.
8. visual_content must describe meaningful visual structure that cannot be represented as ordinary text.
9. important_visual_information must contain visually important information that would be lost if only OCR text were kept.
10. Preserve source claims exactly, even when they appear mathematically or factually incorrect.
11. Do not analyze handwriting style.
12. Do not invent missing information.
13. Use empty arrays only when that type of content is genuinely absent.
14. Keep individual strings reasonably concise, but do not omit visible source content.
"""


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "image_type": {
            "type": "string"
        },
        "visible_text": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },
        "visual_content": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string"
                },
                "elements": {
                    "type": "array",
                    "items": {}
                },
                "relationships": {
                    "type": "array",
                    "items": {}
                }
            },
            "required": [
                "description",
                "elements",
                "relationships"
            ]
        },
        "diagrams": {
            "type": "array",
            "items": {}
        },
        "charts_or_graphs": {
            "type": "array",
            "items": {}
        },
        "tables": {
            "type": "array",
            "items": {}
        },
        "equations_or_formulas": {
            "type": "array",
            "items": {}
        },
        "important_visual_information": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },
        "extraction_notes": {
            "type": "array",
            "items": {
                "type": "string"
            }
        }
    },
    "required": [
        "image_type",
        "visible_text",
        "visual_content",
        "diagrams",
        "charts_or_graphs",
        "tables",
        "equations_or_formulas",
        "important_visual_information",
        "extraction_notes"
    ]
}


def parse_gemini_json(
    output
):

    if isinstance(
        output,
        dict
    ):
        return output

    try:

        return json.loads(
            output
        )

    except json.JSONDecodeError:

        start = output.find(
            "{"
        )

        end = output.rfind(
            "}"
        )

        if (
            start == -1
            or end == -1
            or end <= start
        ):

            raise ValueError(
                "Gemini did not return valid JSON."
            )

        try:

            return json.loads(
                output[
                    start:end + 1
                ]
            )

        except json.JSONDecodeError as error:

            raise ValueError(
                "Gemini returned malformed JSON."
            ) from error


def has_useful_content(
    result
):

    visible_text = result.get(
        "visible_text",
        []
    )

    equations = result.get(
        "equations_or_formulas",
        []
    )

    diagrams = result.get(
        "diagrams",
        []
    )

    charts = result.get(
        "charts_or_graphs",
        []
    )

    tables = result.get(
        "tables",
        []
    )

    important_visual_information = result.get(
        "important_visual_information",
        []
    )

    visual_content = result.get(
        "visual_content",
        {}
    )

    if visible_text:
        return True

    if equations:
        return True

    if diagrams:
        return True

    if charts:
        return True

    if tables:
        return True

    if important_visual_information:
        return True

    if isinstance(
        visual_content,
        dict
    ):

        if visual_content.get(
            "description"
        ):
            return True

        if visual_content.get(
            "elements"
        ):
            return True

        if visual_content.get(
            "relationships"
        ):
            return True

    return False


def extract_visual_content_with_gemini(
    image_bytes: bytes
):

    api_key = os.getenv(
        "GEMINI_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "GEMINI_API_KEY is not configured."
        )

    client = genai.Client(
        api_key=api_key
    )

    image_base64 = base64.b64encode(
        image_bytes
    ).decode(
        "utf-8"
    )

    interaction = client.interactions.create(
        model=MODEL,
        input=[
            {
                "type": "text",
                "text": PROMPT
            },
            {
                "type": "image",
                "data": image_base64,
                "mime_type": "image/png"
            }
        ],
        response_format={
    "type": "text",
    "mime_type": "application/json",
    "schema": RESPONSE_SCHEMA
}
    )

    output = interaction.output_text

    if not output:

        raise ValueError(
            "Gemini returned an empty response."
        )

    result = parse_gemini_json(
        output
    )

    if not isinstance(
        result,
        dict
    ):

        raise ValueError(
            "Gemini returned a non-object JSON response."
        )

    matching_keys = EXPECTED_KEYS.intersection(
        result.keys()
    )

    if len(matching_keys) < 4:

        raise ValueError(
            "Gemini returned an unexpected JSON structure."
        )

    if not has_useful_content(
        result
    ):

        raise ValueError(
            "Gemini returned JSON but no useful visual content."
        )

    return result