import re
from typing import Any


DEFAULT_MAX_CHARS = 1800
DEFAULT_MIN_CHARS = 300


def _split_into_paragraphs(text: str) -> list[str]:
    """
    Split extracted source text into paragraph-like sections.
    """

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    paragraphs = re.split(r"\n\s*\n+", text)

    return [
        paragraph.strip()
        for paragraph in paragraphs
        if paragraph.strip()
    ]


def _split_large_paragraph(text: str, max_chars: int) -> list[str]:
    """
    Split an oversized paragraph at sentence boundaries where possible.
    """

    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()

        if not sentence:
            continue

        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = (
                f"{current} {sentence}".strip()
                if current
                else sentence
            )

    if current:
        chunks.append(current.strip())

    return chunks


def semantic_chunk_text(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[dict[str, Any]]:
    """
    Create practical semantic-ish chunks from source text.

    V1 intentionally avoids an LLM.
    It preserves source wording and groups nearby
    paragraphs without attempting to reinterpret them.
    """

    if not text or not text.strip():
        return []

    paragraphs = _split_into_paragraphs(text)

    expanded = []

    for paragraph in paragraphs:
        expanded.extend(
            _split_large_paragraph(paragraph, max_chars)
        )

    chunks = []
    current_parts = []
    current_length = 0

    for paragraph in expanded:
        paragraph_length = len(paragraph)

        if (
            current_parts
            and current_length + paragraph_length + 2 > max_chars
        ):
            chunks.append("\n\n".join(current_parts))
            current_parts = []
            current_length = 0

        current_parts.append(paragraph)
        current_length += paragraph_length + 2

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    result = []

    for index, chunk in enumerate(chunks):
        chunk = chunk.strip()

        if not chunk:
            continue

        result.append(
            {
                "chunk_index": index,
                "chunk_type": "text",
                "text": chunk,
                "metadata": {
                    "character_count": len(chunk),
                    "short_chunk": len(chunk) < min_chars,
                },
            }
        )

    return result