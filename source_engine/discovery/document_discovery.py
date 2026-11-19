from typing import Any

from source_engine.discovery.models import (
    DiscoveredUnit,
    DiscoveryResult,
)


def _table_to_text(content: Any) -> str:
    """
    Convert a structured table into lightweight searchable text.
    """

    if not isinstance(content, dict):
        return ""

    rows = content.get("rows", [])

    if not isinstance(rows, list):
        return ""

    lines = []

    for row in rows:
        if not isinstance(row, list):
            continue

        cells = [
            str(cell).strip()
            for cell in row
            if str(cell).strip()
        ]

        if cells:
            lines.append(" | ".join(cells))

    return "\n".join(lines)


def _diagram_to_text(content: Any) -> str:
    """
    Extract cheap textual evidence already present inside
    a diagram block.

    We do NOT run vision here.
    """

    if not isinstance(content, dict):
        return ""

    parts = []

    for element in content.get("text_elements", []):
        if not isinstance(element, dict):
            continue

        text = element.get("text", "")

        if text and str(text).strip():
            parts.append(str(text).strip())

    return "\n".join(parts)


def _block_to_discovery_text(block: dict) -> str:
    """
    Convert one SourceDocument content block into cheap
    searchable discovery text.
    """

    block_type = block.get("type")
    content = block.get("content")

    if block_type in {
        "text",
        "equation",
        "visual_description",
        "visual_information",
    }:
        if isinstance(content, str):
            return content.strip()

    if block_type == "table":
        return _table_to_text(content)

    if block_type == "diagram":
        return _diagram_to_text(content)

    # Raw image blocks deliberately contribute no text.
    # Vision is a later/deeper capability.
    return ""


def _summarize_blocks(blocks: list[dict]) -> dict:
    """
    Preserve cheap structural signals for later routing.
    """

    block_counts: dict[str, int] = {}

    has_visual_content = False

    for block in blocks:
        block_type = block.get("type", "unknown")

        block_counts[block_type] = (
            block_counts.get(block_type, 0) + 1
        )

        if block_type in {
            "image",
            "diagram",
            "chart",
        }:
            has_visual_content = True

    return {
        "block_count": len(blocks),
        "block_types": block_counts,
        "has_visual_content": has_visual_content,
    }


def _looks_like_garbled_text(text: str) -> bool:
    """
    Detect obviously corrupted native extraction.

    This is intentionally conservative. The goal is NOT to decide
    whether the text is factually correct. The goal is only to catch
    extraction that is so malformed that it should not be trusted as
    a high-quality discovery representation.
    """

    if not text or not text.strip():
        return False

    cleaned = " ".join(text.split())

    if len(cleaned) < 20:
        return False

    suspicious_characters = {
        "�",
        "Ł",
        "Ï",
        "í",
        "î",
        "ł",
        "Œ",
        "¼",
        "½",
        "¾",
    }

    suspicious_count = sum(
        1
        for char in cleaned
        if char in suspicious_characters
    )

    if suspicious_count >= 2:
        return True

    alphabetic_count = sum(
        1
        for char in cleaned
        if char.isalpha()
    )

    if alphabetic_count == 0:
        return False

    words = cleaned.split()

    if len(words) < 5:
        return False

    normal_words = 0

    for word in words:
        letters = [
            char
            for char in word
            if char.isalpha()
        ]

        if not letters:
            continue

        ascii_letters = sum(
            1
            for char in letters
            if char.isascii()
        )

        if ascii_letters / len(letters) >= 0.8:
            normal_words += 1

    normal_word_ratio = normal_words / max(1, len(words))

    if normal_word_ratio < 0.35:
        return True

    return False


def source_document_to_discovery(
    document: dict,
) -> DiscoveryResult:
    """
    Convert the format-neutral SourceDocument produced by
    DOCX/PPTX/TXT/MD extractors into Lily's persistent
    discovery representation.

    This stage performs no OCR, vision, embeddings,
    chunking, or database writes.
    """

    source_type = document.get(
        "source_type",
        "unknown",
    )

    pages = document.get("pages", [])

    units = []

    for fallback_index, page in enumerate(
        pages,
        start=1,
    ):
        page_number = page.get(
            "page_number",
            fallback_index,
        )

        blocks = page.get(
            "content_blocks",
            [],
        )

        text_parts = []

        for block in blocks:
            text = _block_to_discovery_text(block)

            if text:
                text_parts.append(text)

        discovery_text = "\n\n".join(
            text_parts
        ).strip()

        structural_metadata = _summarize_blocks(
            blocks
        )

        has_text = bool(discovery_text)

        garbled_text = (
            has_text
            and _looks_like_garbled_text(
                discovery_text
            )
        )

        requires_vision = (
            garbled_text
            or (
                structural_metadata["has_visual_content"]
                and not has_text
            )
        )

        if garbled_text:
            discovery_method = (
                f"{source_type}_native_weak"
            )
            discovery_confidence = 0.20

        elif has_text:
            discovery_method = (
                f"{source_type}_native"
            )
            discovery_confidence = 0.95

        else:
            discovery_method = (
                f"{source_type}_structure_only"
            )
            discovery_confidence = 0.50

        units.append(
            DiscoveredUnit(
                unit_index=page_number,
                unit_type=(
                    "slide"
                    if source_type == "pptx"
                    else "document_section"
                ),
                discovery_text=(
                    discovery_text
                    if has_text
                    else None
                ),
                discovery_metadata={
                    "source_type": source_type,
                    "page_number": page_number,
                    **structural_metadata,
                    "page_evidence": page.get(
                        "evidence",
                        {},
                    ),
                    "requires_vision": requires_vision,
                    "native_text_quality": (
                        "weak"
                        if garbled_text
                        else (
                            "good"
                            if has_text
                            else "missing"
                        )
                    ),
                },
                discovery_method=discovery_method,
                discovery_confidence=discovery_confidence,
                discovery_observed=True,
            )
        )

    return DiscoveryResult(
        source_type=source_type,
        units=units,
        metadata={
            "file_name": document.get(
                "file_name"
            ),
            "unit_count": len(units),
            "document_metadata": document.get(
                "metadata",
                {},
            ),
            "discovery_stage": "structured_native",
        },
    )