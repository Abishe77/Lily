from source_engine.source_model import (
    create_content_block,
    create_page,
    create_source_document,
)


def normalize_page(page: dict) -> dict:

    content_blocks = []

    page_number = page.get(
        "page_number"
    )

    order = 1

    native_text = page.get(
        "native_text",
        ""
    ).strip()

    ocr_text = page.get(
        "ocr_text",
        ""
    ).strip()

    # Primary location used by the PDF pipeline.
    qwen_content = page.get(
        "qwen_visual_content"
    )

    # Defensive fallback in case Qwen data has already
    # been placed inside an evidence structure.
    if not qwen_content:

        existing_evidence = page.get(
            "evidence"
        )

        if isinstance(
            existing_evidence,
            dict
        ):

            qwen_content = existing_evidence.get(
                "qwen"
            )

    if not isinstance(
        qwen_content,
        dict
    ):

        qwen_content = None

    # ---------------------------------------------------------
    # Native text
    # ---------------------------------------------------------

    if native_text:

        content_blocks.append(
            create_content_block(
                block_id=f"p{page_number}_b{order}",
                block_type="text",
                content=native_text,
                source="native_text",
                order=order,
                page_number=page_number,
                provenance={
                    "extraction_method": "pymupdf",
                    "source_claim": True
                }
            )
        )

        order += 1

    # ---------------------------------------------------------
    # OCR text
    # ---------------------------------------------------------

    elif ocr_text:

        content_blocks.append(
            create_content_block(
                block_id=f"p{page_number}_b{order}",
                block_type="text",
                content=ocr_text,
                source="ocr",
                order=order,
                page_number=page_number,
                provenance={
                    "extraction_method": "tesseract",
                    "source_claim": True
                }
            )
        )

        order += 1

    # ---------------------------------------------------------
    # Qwen visual extraction
    # ---------------------------------------------------------

    if qwen_content:

        # -----------------------------------------------------
        # Visible text
        # -----------------------------------------------------

        visible_text = qwen_content.get(
            "visible_text",
            []
        )

        if isinstance(
            visible_text,
            list
        ):

            for text in visible_text:

                if not isinstance(
                    text,
                    str
                ):
                    continue

                text = text.strip()

                if not text:
                    continue

                content_blocks.append(
                    create_content_block(
                        block_id=f"p{page_number}_b{order}",
                        block_type="text",
                        content=text,
                        source="qwen",
                        order=order,
                        page_number=page_number,
                        provenance={
                            "extraction_method": "qwen_vision",
                            "source_claim": True
                        }
                    )
                )

                order += 1

        # -----------------------------------------------------
        # Visual content
        # -----------------------------------------------------

        visual_content = qwen_content.get(
            "visual_content",
            {}
        )

        if isinstance(
            visual_content,
            dict
        ):

            description = visual_content.get(
                "description",
                ""
            )

            if isinstance(
                description,
                str
            ):

                description = description.strip()

            else:

                description = ""

            elements = visual_content.get(
                "elements",
                []
            )

            relationships = visual_content.get(
                "relationships",
                []
            )

            has_visual_structure = (
                bool(description)
                or bool(elements)
                or bool(relationships)
            )

            if has_visual_structure:

                content_blocks.append(
                    create_content_block(
                        block_id=f"p{page_number}_b{order}",
                        block_type="visual_description",
                        content={
                            "description": description,
                            "elements": elements,
                            "relationships": relationships
                        },
                        source="qwen",
                        order=order,
                        page_number=page_number,
                        provenance={
                            "extraction_method": "qwen_vision",
                            "source_claim": True
                        }
                    )
                )

                order += 1

        # -----------------------------------------------------
        # Equations
        # -----------------------------------------------------

        equations = qwen_content.get(
            "equations_or_formulas",
            []
        )

        if isinstance(
            equations,
            list
        ):

            for equation in equations:

                if isinstance(
                    equation,
                    str
                ):

                    content = equation.strip()

                elif isinstance(
                    equation,
                    dict
                ):

                    content = equation.get(
                        "description",
                        ""
                    )

                    if isinstance(
                        content,
                        str
                    ):

                        content = content.strip()

                    else:

                        content = ""

                else:

                    continue

                if not content:
                    continue

                if content.lower() == "not observed":
                    continue

                content_blocks.append(
                    create_content_block(
                        block_id=f"p{page_number}_b{order}",
                        block_type="equation",
                        content=content,
                        source="qwen",
                        order=order,
                        page_number=page_number,
                        provenance={
                            "extraction_method": "qwen_vision",
                            "source_claim": True
                        }
                    )
                )

                order += 1

        # -----------------------------------------------------
        # Diagrams
        # -----------------------------------------------------

        diagrams = qwen_content.get(
            "diagrams",
            []
        )

        if isinstance(
            diagrams,
            list
        ):

            for diagram in diagrams:

                if not isinstance(
                    diagram,
                    dict
                ):
                    continue

                description = diagram.get(
                    "description",
                    ""
                )

                if isinstance(
                    description,
                    str
                ):

                    description = description.strip()

                else:

                    description = ""

                labels = diagram.get(
                    "labels",
                    []
                )

                connections = diagram.get(
                    "connections",
                    []
                )

                if not description:
                    continue

                if description.lower() == "not observed":
                    continue

                content_blocks.append(
                    create_content_block(
                        block_id=f"p{page_number}_b{order}",
                        block_type="diagram",
                        content={
                            "description": description,
                            "labels": labels,
                            "connections": connections
                        },
                        source="qwen",
                        order=order,
                        page_number=page_number,
                        provenance={
                            "extraction_method": "qwen_vision",
                            "source_claim": True
                        }
                    )
                )

                order += 1

        # -----------------------------------------------------
        # Tables
        # -----------------------------------------------------

        tables = qwen_content.get(
            "tables",
            []
        )

        if isinstance(
            tables,
            list
        ):

            for table in tables:

                if not isinstance(
                    table,
                    dict
                ):
                    continue

                headers = table.get(
                    "headers",
                    []
                )

                rows = table.get(
                    "rows",
                    []
                )

                if not headers and not rows:
                    continue

                content_blocks.append(
                    create_content_block(
                        block_id=f"p{page_number}_b{order}",
                        block_type="table",
                        content={
                            "headers": headers,
                            "rows": rows
                        },
                        source="qwen",
                        order=order,
                        page_number=page_number,
                        provenance={
                            "extraction_method": "qwen_vision",
                            "source_claim": True
                        }
                    )
                )

                order += 1

        # -----------------------------------------------------
        # Charts / graphs
        # -----------------------------------------------------

        charts = qwen_content.get(
            "charts_or_graphs",
            []
        )

        if isinstance(
            charts,
            list
        ):

            for chart in charts:

                if not isinstance(
                    chart,
                    dict
                ):
                    continue

                description = chart.get(
                    "main_observation",
                    ""
                )

                chart_type = chart.get(
                    "type",
                    ""
                )

                if isinstance(
                    description,
                    str
                ):

                    description = description.strip()

                else:

                    description = ""

                if isinstance(
                    chart_type,
                    str
                ):

                    chart_type = chart_type.strip()

                else:

                    chart_type = ""

                if (
                    not description
                    and not chart_type
                ):
                    continue

                if (
                    description.lower() == "not observed"
                    and chart_type.lower() == "not observed"
                ):
                    continue

                content_blocks.append(
                    create_content_block(
                        block_id=f"p{page_number}_b{order}",
                        block_type="chart",
                        content={
                            "description": description,
                            "chart_type": chart_type,
                            "title": chart.get(
                                "title",
                                ""
                            ),
                            "axes": chart.get(
                                "axes",
                                []
                            ),
                            "visible_values": chart.get(
                                "visible_values",
                                []
                            )
                        },
                        source="qwen",
                        order=order,
                        page_number=page_number,
                        provenance={
                            "extraction_method": "qwen_vision",
                            "source_claim": True
                        }
                    )
                )

                order += 1

        # -----------------------------------------------------
        # Important visual information
        # -----------------------------------------------------

        important_visual_information = qwen_content.get(
            "important_visual_information",
            []
        )

        if isinstance(
            important_visual_information,
            list
        ):

            filtered_visual_information = []

            for item in important_visual_information:

                if isinstance(
                    item,
                    str
                ):

                    item = item.strip()

                    if (
                        item
                        and item.lower() != "not observed"
                    ):

                        filtered_visual_information.append(
                            item
                        )

            if filtered_visual_information:

                content_blocks.append(
                    create_content_block(
                        block_id=f"p{page_number}_b{order}",
                        block_type="visual_information",
                        content=filtered_visual_information,
                        source="qwen",
                        order=order,
                        page_number=page_number,
                        provenance={
                            "extraction_method": "qwen_vision",
                            "source_claim": True
                        }
                    )
                )

                order += 1

    # ---------------------------------------------------------
    # Evidence
    # ---------------------------------------------------------

    evidence = {
        "extraction_method": page.get(
            "extraction_method"
        ),
        "native_text": native_text,
        "ocr": {
            "text": ocr_text,
            "blocks": page.get(
                "ocr_blocks",
                []
            ),
            "lines": page.get(
                "ocr_lines",
                []
            ),
            "quality": page.get(
                "ocr_quality",
                {}
            )
        },
        "page_routing": page.get(
            "page_routing"
        ),
        "detection": page.get(
            "detection"
        ),
        "visual_analysis": page.get(
            "visual_analysis"
        ),
        "qwen": qwen_content,
        "vision_provider": page.get(
            "vision_provider",
            "not_used"
        ),
        "vision_error": page.get(
            "vision_error"
        )
    }

    return create_page(
        page_number=page_number,
        content_blocks=content_blocks,
        dimensions=page.get(
            "dimensions"
        ),
        evidence=evidence
    )


def normalize_pages(
    pages: list
) -> list:

    normalized_pages = []

    for page in pages:

        normalized_pages.append(
            normalize_page(page)
        )

    return normalized_pages


def normalize_pdf_document(
    pages: list,
    file_name: str | None = None
) -> dict:

    normalized_pages = normalize_pages(
        pages
    )

    return create_source_document(
        source_type="pdf",
        file_name=file_name,
        pages=normalized_pages
    )