import base64
import json
import mimetypes
from pathlib import Path
from urllib import request, error


QWEN_SERVER_URL = "http://127.0.0.1:8081/v1/chat/completions"

QWEN_TIMEOUT_SECONDS = 90

MODEL = "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF:Q4_K_M"

EXTRACTION_KEYS = {
    "visible_text",
    "equations_or_formulas",
    "visual_description",
    "unclear_content",
}

DISCOVERY_KEYS = {
    "topic",
    "subtopics",
    "content_type",
    "keywords",
    "contains",
    "short_description",
}


PROMPT = r"""
Read this image as a source document.

Extract the source content that is actually visible.

Do not summarize the subject.
Do not teach the subject.
Do not solve anything.
Do not correct the source.
Do not infer missing information.
Do not invent text.

Preserve handwritten and printed text as faithfully as possible.

Pay special attention to:
- mathematical notation
- superscripts and subscripts
- inequalities
- variables
- repeated characters
- exponents
- set notation
- decomposition of strings
- labels
- arrows
- symbols

If part of the image is genuinely unclear, do not guess.
Put the uncertain reading in "unclear_content".

Return ONLY one valid JSON object with exactly these top-level keys:

{
  "visible_text": [],
  "equations_or_formulas": [],
  "visual_description": "",
  "unclear_content": []
}

Rules:

1. visible_text:
   Preserve all clearly readable source text in natural reading order.

2. equations_or_formulas:
   Preserve mathematical expressions separately when they are clearly visible.

3. visual_description:
   Describe only meaningful non-text visual structure that would otherwise be lost.
   For an ordinary handwritten text page with no meaningful diagram, use an empty string.

4. unclear_content:
   Record text or notation whose exact reading is uncertain.
   Do not silently choose a reading when multiple readings are plausible.

5. Preserve source claims even if they appear mathematically or factually incorrect.

6. Do not produce bounding boxes, coordinates, positions, OCR geometry, or layout coordinates.

7. Do not create element lists or relationship lists.

8. Do not use Markdown.

9. Keep the JSON compact.

10. Return one complete JSON object and nothing else.
"""


RETRY_PROMPT = r"""
Read the source-document image again carefully.

The previous response could not be accepted as a complete source extraction.

Return ONLY one complete valid JSON object:

{
  "visible_text": [],
  "equations_or_formulas": [],
  "visual_description": "",
  "unclear_content": []
}

Extract only what is visibly present.

Do not summarize.
Do not explain.
Do not solve.
Do not correct the source.
Do not invent missing information.

Preserve mathematical notation carefully.

If a character, number, exponent, inequality, word, or expression is uncertain,
put that uncertainty in "unclear_content" instead of confidently inventing it.

Do not return bounding boxes.
Do not return coordinates.
Do not return element objects.
Do not return relationship objects.
Do not return Markdown.

Keep the response compact and complete.
"""


DISCOVERY_PROMPT = r"""
Analyze this source-document page for SEARCH DISCOVERY ONLY.

Do not deeply transcribe the page.

Your job is only to identify what knowledge is roughly present so another system
can later decide whether this page should be deeply extracted.

Return ONLY one valid JSON object:

{
  "topic": "",
  "subtopics": [],
  "content_type": "",
  "keywords": [],
  "contains": [],
  "short_description": ""
}

Requirements:

1. topic:
   Give the main subject or concept in a short phrase.

2. subtopics:
   List important concepts or sections visible on the page.

3. content_type:
   Use a concise description such as:
   "lecture notes",
   "worked mathematical proof",
   "diagram",
   "table",
   "code",
   "definition",
   "mixed study material".

4. keywords:
   Give useful searchable terms.

5. contains:
   Identify structural content such as:
   "equations",
   "proof",
   "diagram",
   "table",
   "worked example",
   "algorithm",
   "code",
   "handwritten notes".

6. short_description:
   Briefly describe what knowledge appears on the page.

Prefer semantic discovery over transcription.

Do not solve or correct the source.

Do not invent information.

If the topic cannot be determined confidently, use "unknown".

Do not use Markdown.

Return one complete valid JSON object and nothing else.
"""


def _image_to_data_url(image_path):
    path = Path(image_path)

    image_bytes = path.read_bytes()

    mime_type, _ = mimetypes.guess_type(path.name)

    if not mime_type:
        mime_type = "image/png"

    encoded = base64.b64encode(
        image_bytes
    ).decode("ascii")

    return f"data:{mime_type};base64,{encoded}"


def run_qwen(
    image_path,
    prompt,
    max_tokens=1536,
):
    image_url = _image_to_data_url(
        image_path
    )

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                        },
                    },
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": False,
    }

    encoded_payload = json.dumps(
        payload
    ).encode("utf-8")

    http_request = request.Request(
        QWEN_SERVER_URL,
        data=encoded_payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(
            http_request,
            timeout=QWEN_TIMEOUT_SECONDS,
        ) as response:
            response_body = (
                response
                .read()
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )

    except error.HTTPError as exc:
        response_body = (
            exc.read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        raise RuntimeError(
            "Qwen server returned "
            f"HTTP {exc.code}:\n"
            f"{response_body}"
        ) from exc

    except error.URLError as exc:
        raise RuntimeError(
            "Could not connect to the Qwen "
            "vision server at "
            f"{QWEN_SERVER_URL}. "
            "Make sure llama-server is running."
        ) from exc

    except TimeoutError as exc:
        raise TimeoutError(
            "Qwen server inference timed out after "
            f"{QWEN_TIMEOUT_SECONDS} seconds."
        ) from exc

    try:
        response_json = json.loads(
            response_body
        )

        output = (
            response_json["choices"][0]
            ["message"]["content"]
        )

    except (
        json.JSONDecodeError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise ValueError(
            "Qwen server returned an unexpected "
            f"response:\n{response_body}"
        ) from exc

    if not isinstance(output, str):
        raise ValueError(
            "Qwen server returned non-text "
            "assistant content."
        )

    return output.strip()


def _strip_markdown_fence(text):
    cleaned = text.strip()

    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")

        if first_newline != -1:
            cleaned = cleaned[
                first_newline + 1:
            ]

        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    return cleaned.strip()


def parse_json_object(output):
    cleaned = _strip_markdown_fence(
        output
    )

    try:
        result = json.loads(
            cleaned
        )

    except json.JSONDecodeError as exc:
        raise ValueError(
            "Qwen did not return one complete "
            "valid JSON object.\n\n"
            f"Output:\n{output}"
        ) from exc

    if not isinstance(result, dict):
        raise ValueError(
            "Qwen response JSON must be "
            "an object."
        )

    return result


def validate_extraction_result(result):
    missing_keys = (
        EXTRACTION_KEYS
        - result.keys()
    )

    if missing_keys:
        raise ValueError(
            "Qwen extraction response is "
            f"missing keys: {missing_keys}"
        )

    extra_keys = (
        result.keys()
        - EXTRACTION_KEYS
    )

    if extra_keys:
        raise ValueError(
            "Qwen extraction response contains "
            f"unexpected keys: {extra_keys}"
        )

    visible_text = result.get(
        "visible_text"
    )

    equations = result.get(
        "equations_or_formulas"
    )

    visual_description = result.get(
        "visual_description"
    )

    unclear_content = result.get(
        "unclear_content"
    )

    if not isinstance(
        visible_text,
        list,
    ):
        raise ValueError(
            "visible_text must be a list."
        )

    if not isinstance(
        equations,
        list,
    ):
        raise ValueError(
            "equations_or_formulas must be "
            "a list."
        )

    if not isinstance(
        visual_description,
        str,
    ):
        raise ValueError(
            "visual_description must be "
            "a string."
        )

    if not isinstance(
        unclear_content,
        list,
    ):
        raise ValueError(
            "unclear_content must be a list."
        )

    useful_visible_text = [
        item
        for item in visible_text
        if isinstance(item, str)
        and item.strip()
    ]

    useful_equations = [
        item
        for item in equations
        if isinstance(item, str)
        and item.strip()
    ]

    useful_unclear = [
        item
        for item in unclear_content
        if isinstance(item, str)
        and item.strip()
    ]

    if (
        not useful_visible_text
        and not useful_equations
        and not visual_description.strip()
        and not useful_unclear
    ):
        raise ValueError(
            "Qwen returned a valid extraction "
            "schema but no useful source content."
        )

    return {
        "visible_text": useful_visible_text,
        "equations_or_formulas": useful_equations,
        "visual_description": (
            visual_description.strip()
        ),
        "unclear_content": useful_unclear,
    }


def extract_visual_content(
    image_path,
):
    output = run_qwen(
        image_path,
        PROMPT,
        max_tokens=1536,
    )

    print(
        "\n===== QWEN VISION FIRST RAW OUTPUT ====="
    )
    print(output)
    print(
        "===== END QWEN VISION FIRST RAW OUTPUT =====\n"
    )

    try:
        result = parse_json_object(
            output
        )

        result = validate_extraction_result(
            result
        )

        print(
            "[qwen-vision] "
            "First extraction accepted."
        )

        return result

    except ValueError as exc:
        print(
            "[qwen-vision] "
            f"First extraction rejected: {exc}"
        )

    retry_output = run_qwen(
        image_path,
        RETRY_PROMPT,
        max_tokens=1536,
    )

    print(
        "\n===== QWEN VISION RETRY RAW OUTPUT ====="
    )
    print(retry_output)
    print(
        "===== END QWEN VISION RETRY RAW OUTPUT =====\n"
    )

    retry_result = parse_json_object(
        retry_output
    )

    retry_result = validate_extraction_result(
        retry_result
    )

    print(
        "[qwen-vision] "
        "Retry extraction accepted."
    )

    return retry_result


def discover_visual_content(
    image_path,
):
    output = run_qwen(
        image_path,
        DISCOVERY_PROMPT,
        max_tokens=512,
    )

    result = parse_json_object(
        output
    )

    missing_keys = (
        DISCOVERY_KEYS
        - result.keys()
    )

    if missing_keys:
        raise ValueError(
            "Qwen discovery response is "
            f"missing keys: {missing_keys}"
        )

    extra_keys = (
        result.keys()
        - DISCOVERY_KEYS
    )

    if extra_keys:
        raise ValueError(
            "Qwen discovery response contains "
            f"unexpected keys: {extra_keys}"
        )

    if not isinstance(
        result.get("topic"),
        str,
    ):
        raise ValueError(
            "Qwen discovery topic must be "
            "a string."
        )

    if not isinstance(
        result.get("subtopics"),
        list,
    ):
        raise ValueError(
            "Qwen discovery subtopics must "
            "be a list."
        )

    if not isinstance(
        result.get("content_type"),
        str,
    ):
        raise ValueError(
            "Qwen discovery content_type "
            "must be a string."
        )

    if not isinstance(
        result.get("keywords"),
        list,
    ):
        raise ValueError(
            "Qwen discovery keywords must "
            "be a list."
        )

    if not isinstance(
        result.get("contains"),
        list,
    ):
        raise ValueError(
            "Qwen discovery contains must "
            "be a list."
        )

    if not isinstance(
        result.get("short_description"),
        str,
    ):
        raise ValueError(
            "Qwen discovery short_description "
            "must be a string."
        )

    return result
