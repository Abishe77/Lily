import tempfile
from pathlib import Path

import pymupdf

from source_engine.qwen_vision import (
    discover_visual_content,
)


DISCOVERY_VISION_RENDER_SCALE = 1.25
MAX_VISION_DISCOVERY_CHARS = 2000


def _clean_text(value) -> str:
    if not isinstance(value, str):
        return ""

    return " ".join(value.split()).strip()


def _build_discovery_text(
    discovery_result: dict,
) -> str:
    """
    Convert Qwen's lightweight discovery JSON
    into compact searchable text.

    This is NOT deep extraction.
    """

    parts = []

    topic = _clean_text(
        discovery_result.get("topic", "")
    )

    if topic and topic.lower() != "unknown":
        parts.append(
            f"Topic: {topic}"
        )

    subtopics = discovery_result.get(
        "subtopics",
        []
    )

    if isinstance(subtopics, list):
        cleaned_subtopics = []

        for item in subtopics:
            text = _clean_text(item)

            if text:
                cleaned_subtopics.append(text)

        if cleaned_subtopics:
            parts.append(
                "Subtopics: "
                + ", ".join(cleaned_subtopics)
            )

    content_type = _clean_text(
        discovery_result.get(
            "content_type",
            ""
        )
    )

    if content_type:
        parts.append(
            f"Content type: {content_type}"
        )

    keywords = discovery_result.get(
        "keywords",
        []
    )

    if isinstance(keywords, list):
        cleaned_keywords = []

        for item in keywords:
            text = _clean_text(item)

            if text:
                cleaned_keywords.append(text)

        if cleaned_keywords:
            parts.append(
                "Keywords: "
                + ", ".join(cleaned_keywords)
            )

    contains = discovery_result.get(
        "contains",
        []
    )

    if isinstance(contains, list):
        cleaned_contains = []

        for item in contains:
            text = _clean_text(item)

            if text:
                cleaned_contains.append(text)

        if cleaned_contains:
            parts.append(
                "Contains: "
                + ", ".join(cleaned_contains)
            )

    short_description = _clean_text(
        discovery_result.get(
            "short_description",
            ""
        )
    )

    if short_description:
        parts.append(
            f"Description: {short_description}"
        )

    discovery_text = "\n".join(parts).strip()

    return discovery_text[:MAX_VISION_DISCOVERY_CHARS]


def _run_discovery_on_image(
    image_bytes: bytes,
) -> dict:

    temporary_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".png",
            delete=False,
        ) as temporary_file:

            temporary_path = Path(
                temporary_file.name
            )

            temporary_file.write(
                image_bytes
            )

        return discover_visual_content(
            str(temporary_path)
        )

    finally:

        if (
            temporary_path
            and temporary_path.exists()
        ):
            temporary_path.unlink()

def discover_image_with_vision(
    image_bytes: bytes,
) -> dict:
    """
    Run lightweight Qwen vision discovery directly on
    a standalone image.

    This is discovery only, not deep ingestion.
    """

    if not image_bytes:
        return {
            "text": None,
            "useful": False,
            "provider": "qwen",
        }

    discovery_result = _run_discovery_on_image(
        image_bytes
    )

    if not isinstance(
        discovery_result,
        dict,
    ):
        return {
            "text": None,
            "useful": False,
            "provider": "qwen",
        }

    discovery_text = _build_discovery_text(
        discovery_result
    )

    useful = len(
        discovery_text
    ) >= 30

    return {
        "text": (
            discovery_text
            if discovery_text
            else None
        ),
        "useful": useful,
        "provider": "qwen",
    }            


def discover_page_with_vision(
    page: pymupdf.Page,
) -> dict:

    matrix = pymupdf.Matrix(
        DISCOVERY_VISION_RENDER_SCALE,
        DISCOVERY_VISION_RENDER_SCALE,
    )

    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False,
    )

    image_bytes = pixmap.tobytes(
        "png"
    )

    discovery_result = (
        _run_discovery_on_image(
            image_bytes
        )
    )

    if not isinstance(
        discovery_result,
        dict,
    ):
        return {
            "text": None,
            "useful": False,
            "provider": "qwen",
            "render_scale": (
                DISCOVERY_VISION_RENDER_SCALE
            ),
        }

    discovery_text = (
        _build_discovery_text(
            discovery_result
        )
    )

    useful = len(
        discovery_text
    ) >= 30

    return {
        "text": (
            discovery_text
            if discovery_text
            else None
        ),
        "useful": useful,
        "provider": "qwen",
        "render_scale": (
            DISCOVERY_VISION_RENDER_SCALE
        ),
    }