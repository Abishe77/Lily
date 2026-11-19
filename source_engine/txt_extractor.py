from source_engine.source_model import (
    create_content_block,
    create_page,
    create_source_document,
)


def extract_txt(
    file_bytes: bytes,
    file_name: str | None = None
) -> dict:

    text = file_bytes.decode(
        "utf-8",
        errors="replace"
    ).strip()

    block = create_content_block(
        block_id="p1_b1",
        block_type="text",
        content=text,
        source="txt",
        order=1,
        page_number=1,
        provenance={
            "extraction_method": "utf8"
        }
    )

    page = create_page(
        page_number=1,
        content_blocks=[block],
        evidence={
            "extraction_method": "utf8"
        }
    )

    return create_source_document(
        source_type="txt",
        file_name=file_name,
        pages=[page]
    )