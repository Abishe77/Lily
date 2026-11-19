import pymupdf

from .models import (
    DiscoveredUnit,
    DiscoveryResult,
)

from .ocr_discovery import (
    discover_page_with_ocr,
)

from .vision_discovery import (
    discover_page_with_vision,
)


MAX_NATIVE_DISCOVERY_CHARS = 4000


def _clean_native_text(
    text: str
) -> str:

    if not text:
        return ""

    lines = []

    for line in text.splitlines():

        cleaned = " ".join(
            line.split()
        ).strip()

        if cleaned:
            lines.append(
                cleaned
            )

    return "\n".join(
        lines
    ).strip()


def _native_text_quality(
    text: str
) -> float:

    if not text:
        return 0.0

    length = len(text)

    if length < 20:
        return 0.15

    alphanumeric = sum(
        character.isalnum()
        for character in text
    )

    ratio = (
        alphanumeric
        / max(length, 1)
    )

    if (
        length >= 150
        and ratio >= 0.45
    ):
        return 0.95

    if (
        length >= 60
        and ratio >= 0.35
    ):
        return 0.75

    if (
        length >= 20
        and ratio >= 0.25
    ):
        return 0.50

    return 0.25


def discover_pdf(
    file_bytes: bytes
) -> DiscoveryResult:

    document = pymupdf.open(
        stream=file_bytes,
        filetype="pdf"
    )

    units: list[
        DiscoveredUnit
    ] = []

    native_pages = 0
    ocr_pages = 0
    vision_pages = 0
    unresolved_pages = 0

    try:

        total_pages = (
            document.page_count
        )

        for page_index in range(
            total_pages
        ):

            page = document.load_page(
                page_index
            )

            # =================================================
            # STAGE 1 — NATIVE TEXT
            # =================================================

            raw_native_text = (
                page.get_text(
                    "text"
                )
            )

            native_text = (
                _clean_native_text(
                    raw_native_text
                )
            )

            native_confidence = (
                _native_text_quality(
                    native_text
                )
            )

            if (
                native_confidence
                >= 0.50
            ):

                native_pages += 1

                units.append(
                    DiscoveredUnit(
                        unit_index=(
                            page_index + 1
                        ),
                        unit_type="page",
                        discovery_text=(
                            native_text[
                                :MAX_NATIVE_DISCOVERY_CHARS
                            ]
                        ),
                        discovery_metadata={
                            "native_character_count":
                                len(
                                    native_text
                                ),
                            "requires_fallback":
                                False,
                            "requires_vision":
                                False,
                        },
                        discovery_method=(
                            "native"
                        ),
                        discovery_confidence=(
                            native_confidence
                        ),
                        discovery_observed=True,
                    )
                )

                continue

            # =================================================
            # STAGE 2 — CHEAP OCR
            #
            # Only weak native pages reach this point.
            # =================================================

            ocr_result = (
                discover_page_with_ocr(
                    page
                )
            )

            if ocr_result[
                "useful"
            ]:

                ocr_pages += 1

                discovery_confidence = min(
                    max(
                        ocr_result[
                            "quality"
                        ][
                            "average_confidence"
                        ]
                        / 100.0,
                        0.0
                    ),
                    1.0
                )

                units.append(
                    DiscoveredUnit(
                        unit_index=(
                            page_index + 1
                        ),
                        unit_type="page",
                        discovery_text=(
                            ocr_result[
                                "text"
                            ]
                        ),
                        discovery_metadata={
                            "native_character_count":
                                len(
                                    native_text
                                ),
                            "ocr_quality":
                                ocr_result[
                                    "quality"
                                ],
                            "ocr_render_scale":
                                ocr_result[
                                    "render_scale"
                                ],
                            "requires_fallback":
                                False,
                            "requires_vision":
                                False,
                        },
                        discovery_method=(
                            "ocr"
                        ),
                        discovery_confidence=(
                            discovery_confidence
                        ),
                        discovery_observed=True,
                    )
                )

                continue

            # =================================================
            # STAGE 3 — QWEN VISION
            #
            # Only pages that failed both:
            #
            #   native text
            #   cheap OCR
            #
            # reach this point.
            # =================================================

            try:

                vision_result = (
                    discover_page_with_vision(
                        page
                    )
                )

            except Exception as exc:

                unresolved_pages += 1

                fallback_text = (
                    ocr_result[
                        "text"
                    ]
                    or (
                        native_text[
                            :MAX_NATIVE_DISCOVERY_CHARS
                        ]
                        if native_text
                        else None
                    )
                )

                units.append(
                    DiscoveredUnit(
                        unit_index=(
                            page_index + 1
                        ),
                        unit_type="page",
                        discovery_text=(
                            fallback_text
                        ),
                        discovery_metadata={
                            "native_character_count":
                                len(
                                    native_text
                                ),
                            "ocr_quality":
                                ocr_result[
                                    "quality"
                                ],
                            "ocr_render_scale":
                                ocr_result[
                                    "render_scale"
                                ],
                            "vision_attempted":
                                True,
                            "vision_error":
                                str(
                                    exc
                                ),
                            "requires_fallback":
                                True,
                            "requires_vision":
                                True,
                        },
                        discovery_method=(
                            "vision_failed"
                        ),
                        discovery_confidence=(
                            0.0
                        ),
                        discovery_observed=True,
                    )
                )

                continue

            # =================================================
            # QWEN PRODUCED USEFUL DISCOVERY INFORMATION
            # =================================================

            if vision_result[
                "useful"
            ]:

                vision_pages += 1

                units.append(
                    DiscoveredUnit(
                        unit_index=(
                            page_index + 1
                        ),
                        unit_type="page",
                        discovery_text=(
                            vision_result[
                                "text"
                            ]
                        ),
                        discovery_metadata={
                            "native_character_count":
                                len(
                                    native_text
                                ),
                            "ocr_quality":
                                ocr_result[
                                    "quality"
                                ],
                            "ocr_render_scale":
                                ocr_result[
                                    "render_scale"
                                ],
                            "vision_provider":
                                vision_result[
                                    "provider"
                                ],
                            "vision_render_scale":
                                vision_result[
                                    "render_scale"
                                ],
                            "vision_attempted":
                                True,
                            "requires_fallback":
                                False,
                            "requires_vision":
                                False,
                        },
                        discovery_method=(
                            "qwen_vision"
                        ),

                        # This is discovery confidence,
                        # NOT factual certainty.
                        discovery_confidence=(
                            0.90
                        ),

                        discovery_observed=True,
                    )
                )

                continue

            # =================================================
            # STAGE 3 ALSO FAILED
            # =================================================

            unresolved_pages += 1

            fallback_text = (
                vision_result[
                    "text"
                ]
                or ocr_result[
                    "text"
                ]
                or (
                    native_text[
                        :MAX_NATIVE_DISCOVERY_CHARS
                    ]
                    if native_text
                    else None
                )
            )

            units.append(
                DiscoveredUnit(
                    unit_index=(
                        page_index + 1
                    ),
                    unit_type="page",
                    discovery_text=(
                        fallback_text
                    ),
                    discovery_metadata={
                        "native_character_count":
                            len(
                                native_text
                            ),
                        "ocr_quality":
                            ocr_result[
                                "quality"
                            ],
                        "ocr_render_scale":
                            ocr_result[
                                "render_scale"
                            ],
                        "vision_provider":
                            vision_result[
                                "provider"
                            ],
                        "vision_render_scale":
                            vision_result[
                                "render_scale"
                            ],
                        "vision_attempted":
                            True,
                        "requires_fallback":
                            True,
                        "requires_vision":
                            False,
                    },
                    discovery_method=(
                        "vision_weak"
                    ),
                    discovery_confidence=(
                        0.0
                    ),
                    discovery_observed=True,
                )
            )

        return DiscoveryResult(
            source_type="pdf",
            units=units,
            metadata={
                "page_count":
                    total_pages,
                "native_pages":
                    native_pages,
                "ocr_pages":
                    ocr_pages,
                "vision_pages":
                    vision_pages,
                "unresolved_pages":
                    unresolved_pages,
                "discovery_stage":
                    "native+ocr+vision",
            }
        )

    finally:

        document.close()


# =========================================================
# TEMPORARY BACKWARD-COMPATIBILITY ALIAS
#
# Existing test script still imports:
#
#     discover_pdf_native
#
# Keep it working while discovery evolves.
# =========================================================

discover_pdf_native = discover_pdf