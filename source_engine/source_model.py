from typing import Any


CONTENT_TYPES = {
    "text",
    "equation",
    "table",
    "diagram",
    "chart",
    "image",
    "visual_description",
    "visual_information",
}


SOURCE_TYPES = {
    "pdf",
    "docx",
    "pptx",
    "txt",
    "md",
}


def create_content_block(
    block_id: str,
    block_type: str,
    content: Any,
    source: str,
    order: int,
    page_number: int | None = None,
    location: dict | None = None,
    provenance: dict | None = None,
) -> dict:

    if block_type not in CONTENT_TYPES:
        raise ValueError(
            f"Unsupported content type: {block_type}"
        )

    return {
        "block_id": block_id,
        "type": block_type,
        "content": content,
        "source": source,
        "order": order,
        "page_number": page_number,
        "location": location,
        "provenance": provenance or {},
    }


def create_page(
    page_number: int,
    content_blocks: list[dict],
    dimensions: dict | None = None,
    evidence: dict | None = None,
) -> dict:

    return {
        "page_number": page_number,
        "dimensions": dimensions or {},
        "content_blocks": content_blocks,
        "evidence": evidence or {},
    }


def create_source_document(
    source_type: str,
    file_name: str | None,
    pages: list[dict],
    metadata: dict | None = None,
) -> dict:

    if source_type not in SOURCE_TYPES:
        raise ValueError(
            f"Unsupported source type: {source_type}"
        )

    return {
        "source_type": source_type,
        "file_name": file_name,
        "metadata": metadata or {},
        "pages": pages,
    }