def get_visual_blocks(
    source_type: str,
    page: dict,
) -> list[dict]:
    """
    Return canonical content blocks that should be processed
    by a vision model.

    DOCX diagrams are intentionally excluded here because their
    native DrawingML structure and text have already been extracted.
    Only standalone raster images are sent to Qwen.

    PDF routing is handled separately by the PDF pipeline.
    """

    visual_blocks = []

    for block in page.get(
        "content_blocks",
        []
    ):

        block_type = block.get(
            "type"
        )

        if block_type != "image":
            continue

        content = block.get(
            "content",
            {}
        )

        if not isinstance(
            content,
            dict
        ):
            continue

        if not content.get(
            "image_bytes"
        ):
            continue

        visual_blocks.append(
            block
        )

    return visual_blocks


def should_use_qwen(
    source_type: str,
    page: dict,
) -> bool:

    if source_type == "pdf":

        detection = page.get(
            "detection",
            {}
        )

        return bool(
            detection.get(
                "needs_visual_analysis",
                False
            )
        )

    return bool(
        get_visual_blocks(
            source_type,
            page,
        )
    )