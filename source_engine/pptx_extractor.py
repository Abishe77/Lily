from io import BytesIO

from pptx import Presentation

from source_engine.source_model import (
    create_content_block,
    create_page,
    create_source_document,
)


def extract_pptx(
    file_bytes: bytes,
    file_name: str | None = None
) -> dict:

    presentation = Presentation(
        BytesIO(file_bytes)
    )

    pages = []

    for slide_number, slide in enumerate(
        presentation.slides,
        start=1
    ):

        content_blocks = []
        order = 1
        image_count = 0

        for shape in slide.shapes:

            if hasattr(
                shape,
                "text"
            ):

                text = shape.text.strip()

                if text:

                    content_blocks.append(
                        create_content_block(
                            block_id=f"p{slide_number}_b{order}",
                            block_type="text",
                            content=text,
                            source="pptx",
                            order=order,
                            page_number=slide_number,
                            provenance={
                                "extraction_method": "python-pptx"
                            }
                        )
                    )

                    order += 1

            if shape.shape_type == 13:

                image = shape.image

                image_bytes = image.blob

                image_count += 1

                content_blocks.append(
                    create_content_block(
                        block_id=f"p{slide_number}_b{order}",
                        block_type="image",
                        content={
                            "mime_type": image.content_type,
                            "size_bytes": len(image_bytes),
                            "image_bytes": image_bytes
                        },
                        source="pptx",
                        order=order,
                        page_number=slide_number,
                        location={
                            "left": shape.left,
                            "top": shape.top,
                            "width": shape.width,
                            "height": shape.height
                        },
                        provenance={
                            "extraction_method": "python-pptx",
                            "visual_content": True,
                            "image_index": image_count
                        }
                    )
                )

                order += 1

        pages.append(
            create_page(
                page_number=slide_number,
                content_blocks=content_blocks,
                dimensions={
                    "width": presentation.slide_width,
                    "height": presentation.slide_height
                },
                evidence={
                    "extraction_method": "python-pptx",
                    "image_count": image_count
                }
            )
        )

    return create_source_document(
        source_type="pptx",
        file_name=file_name,
        pages=pages
    )