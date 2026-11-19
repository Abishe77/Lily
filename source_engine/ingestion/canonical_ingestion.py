from typing import Any


def build_native_canonical_content(
    discovery_text: str,
    unit_index: int,
    unit_type: str,
) -> dict[str, Any]:
    """
    Build the initial canonical representation for a digitally
    extracted source unit.

    This intentionally preserves the source text rather than
    inventing additional interpretation.
    """

    if not discovery_text or not discovery_text.strip():
        raise ValueError("Cannot build canonical content from empty text.")

    return {
        "unit_index": unit_index,
        "unit_type": unit_type,
        "blocks": [
            {
                "type": "text",
                "content": discovery_text.strip(),
            }
        ],
    }


def build_retrieval_text(canonical_content: dict[str, Any]) -> str:
    """
    Convert canonical content into text suitable for embedding
    and retrieval.
    """

    blocks = canonical_content.get("blocks", [])

    parts = []

    for block in blocks:
        content = block.get("content")

        if content:
            parts.append(str(content).strip())

        description = block.get("description")

        if description:
            parts.append(str(description).strip())

    return "\n\n".join(
        part for part in parts
        if part
    )