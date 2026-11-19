
def classify_docx_document(
    document: dict
) -> dict:
    """
    Classify a DOCX document into:

        text_first
        hybrid
        visual_first
        unknown

    The router works from the canonical content blocks
    produced by docx_extractor.py.

    It only decides what kind of processing the document
    needs. It does not perform OCR or vision itself.
    """

    pages = document.get("pages", [])

    if not pages:
        return {
            "classification": "unknown",
            "confidence": "low",
            "reason": "no_pages_found",
            "signals": {
                "page_count": 0,
                "text_blocks": 0,
                "image_blocks": 0,
                "table_blocks": 0,
                "text_characters": 0,
                "image_bytes": 0
            }
        }

    text_blocks = 0
    image_blocks = 0
    table_blocks = 0

    text_characters = 0
    image_bytes = 0

    for page in pages:

        for block in page.get(
            "content_blocks",
            []
        ):

            # source_model.py uses "type", not "block_type".
            block_type = block.get(
                "type"
            )

            if block_type == "text":

                text_blocks += 1

                content = block.get(
                    "content",
                    ""
                )

                if isinstance(
                    content,
                    str
                ):
                    text_characters += len(
                        content.strip()
                    )

            elif block_type == "image":

                image_blocks += 1

                content = block.get(
                    "content",
                    {}
                )

                if isinstance(
                    content,
                    dict
                ):
                    image_bytes += content.get(
                        "size_bytes",
                        0
                    )

            elif block_type == "table":

                table_blocks += 1

    has_text = (
        text_blocks > 0
        and text_characters > 0
    )

    has_images = image_blocks > 0
    has_tables = table_blocks > 0

    signals = {
        "page_count": len(pages),
        "text_blocks": text_blocks,
        "text_characters": text_characters,
        "image_blocks": image_blocks,
        "image_bytes": image_bytes,
        "table_blocks": table_blocks
    }

   

    if has_text and has_images:

        return {
            "classification": "hybrid",
            "confidence": "high",
            "reason": "text_with_embedded_images",
            "signals": signals
        }

    

    if has_text and has_tables:

        return {
            "classification": "text_first",
            "confidence": "high",
            "reason": "text_with_structured_tables",
            "signals": signals
        }

   

    if has_text:

        return {
            "classification": "text_first",
            "confidence": "high",
            "reason": "text_only_document",
            "signals": signals
        }

   

    if has_images:

        return {
            "classification": "visual_first",
            "confidence": "high",
            "reason": "images_without_text",
            "signals": signals
        }

 

    if has_tables:

        return {
            "classification": "text_first",
            "confidence": "high",
            "reason": "structured_tables_without_text_blocks",
            "signals": signals
        }

   

    return {
        "classification": "unknown",
        "confidence": "low",
        "reason": "no_extractable_content",
        "signals": signals
    }



