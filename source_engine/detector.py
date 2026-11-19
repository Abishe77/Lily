
def detect_information_loss(page):
    native_text = page.get(
        "native_text",
        ""
    ).strip()

    ocr_text = page.get(
        "ocr_text",
        ""
    ).strip()

    ocr_quality = page.get(
        "ocr_quality",
        {}
    )

    average_confidence = ocr_quality.get(
        "average_confidence",
        0.0
    )

    low_confidence_ratio = ocr_quality.get(
        "low_confidence_ratio",
        1.0
    )

    character_count = ocr_quality.get(
        "character_count",
        0
    )

    block_count = ocr_quality.get(
        "block_count",
        0
    )

    signals = {
        "native_text_available": bool(
            native_text
        ),
        "ocr_character_count": character_count,
        "ocr_block_count": block_count,
        "ocr_average_confidence": round(
            average_confidence,
            2
        ),
        "ocr_low_confidence_ratio": round(
            low_confidence_ratio,
            3
        )
    }

    if native_text:
        return {
            "needs_visual_analysis": False,
            "reason": "native_text_available",
            "signals": signals
        }

    if not ocr_text:
        return {
            "needs_visual_analysis": True,
            "reason": "no_text_recovered",
            "signals": signals
        }

    if average_confidence < 50:
        return {
            "needs_visual_analysis": True,
            "reason": "ocr_quality_low",
            "signals": signals
        }

    if low_confidence_ratio > 0.50:
        return {
            "needs_visual_analysis": True,
            "reason": "too_many_low_confidence_words",
            "signals": signals
        }

    if character_count < 20 and block_count < 5:
        return {
            "needs_visual_analysis": True,
            "reason": "insufficient_text_recovered",
            "signals": signals
        }

    return {
        "needs_visual_analysis": False,
        "reason": "text_extraction_sufficient",
        "signals": signals
    }

