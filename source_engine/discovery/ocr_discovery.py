import io

import pymupdf
from PIL import Image
import pytesseract
from pytesseract import Output


# Discovery OCR deliberately renders lower than the deep
# extractor's 1.5x render.
DISCOVERY_OCR_RENDER_SCALE = 1.0

MAX_OCR_DISCOVERY_CHARS = 4000


def _group_ocr_words(data: dict) -> list[dict]:
    """
    Convert Tesseract's word-level output into readable lines.

    This is intentionally lightweight. Discovery does not need
    the richer block/bbox representation used by deep ingestion.
    """

    lines = {}

    for index in range(len(data["text"])):

        text = data["text"][index].strip()

        if not text:
            continue

        try:
            confidence = float(
                data["conf"][index]
            )
        except (TypeError, ValueError):
            confidence = -1.0

        key = (
            data["block_num"][index],
            data["par_num"][index],
            data["line_num"][index],
        )

        lines.setdefault(
            key,
            []
        ).append(
            {
                "text": text,
                "confidence": confidence,
            }
        )

    result = []

    for words in lines.values():

        text = " ".join(
            word["text"]
            for word in words
        ).strip()

        valid_confidences = [
            word["confidence"]
            for word in words
            if word["confidence"] >= 0
        ]

        if valid_confidences:
            confidence = (
                sum(valid_confidences)
                / len(valid_confidences)
            )
        else:
            confidence = 0.0

        result.append(
            {
                "text": text,
                "confidence": confidence,
                "word_count": len(words),
            }
        )

    return result


def _calculate_discovery_ocr_quality(
    lines: list[dict]
) -> dict:
    """
    Cheap quality estimate used only for deciding whether OCR
    produced enough information for discovery.

    This is NOT a deep-ingestion confidence score.
    """

    if not lines:
        return {
            "score": 0.0,
            "average_confidence": 0.0,
            "low_confidence_ratio": 1.0,
            "character_count": 0,
            "word_count": 0,
        }

    confidences = []

    character_count = 0
    word_count = 0

    for line in lines:

        character_count += len(
            line["text"]
        )

        word_count += line["word_count"]

        confidences.extend(
            [line["confidence"]]
            * line["word_count"]
        )

    if not confidences:
        average_confidence = 0.0
        low_confidence_ratio = 1.0
    else:
        average_confidence = (
            sum(confidences)
            / len(confidences)
        )

        low_confidence_ratio = (
            sum(
                1
                for confidence in confidences
                if confidence < 50
            )
            / len(confidences)
        )

    return {
        "score": round(
            average_confidence,
            2
        ),
        "average_confidence": round(
            average_confidence,
            2
        ),
        "low_confidence_ratio": round(
            low_confidence_ratio,
            4
        ),
        "character_count": character_count,
        "word_count": word_count,
    }


def _is_ocr_useful(
    quality: dict
) -> bool:
    """
    Decide whether OCR produced enough signal for coarse
    discovery.

    We're intentionally less strict than deep ingestion.
    """

    character_count = quality[
        "character_count"
    ]

    average_confidence = quality[
        "average_confidence"
    ]

    low_confidence_ratio = quality[
        "low_confidence_ratio"
    ]

    if (
        character_count >= 80
        and average_confidence >= 55
        and low_confidence_ratio <= 0.60
    ):
        return True

    if (
        character_count >= 30
        and average_confidence >= 70
    ):
        return True

    return False


def discover_page_with_ocr(
    page: pymupdf.Page
) -> dict:
    """
    Perform cheap OCR discovery on ONE PDF page.

    Called only after native-text discovery has failed.

    No Qwen.
    No Gemini.
    No canonical normalization.
    No persistent rendered image.
    """

    matrix = pymupdf.Matrix(
        DISCOVERY_OCR_RENDER_SCALE,
        DISCOVERY_OCR_RENDER_SCALE
    )

    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    image_bytes = pixmap.tobytes(
        "png"
    )

    image = Image.open(
        io.BytesIO(
            image_bytes
        )
    )

    try:

        ocr_data = pytesseract.image_to_data(
            image,
            output_type=Output.DICT
        )

    finally:

        image.close()

    lines = _group_ocr_words(
        ocr_data
    )

    ocr_text = "\n".join(
        line["text"]
        for line in lines
    ).strip()

    quality = _calculate_discovery_ocr_quality(
        lines
    )

    useful = _is_ocr_useful(
        quality
    )

    return {
        "text": (
            ocr_text[
                :MAX_OCR_DISCOVERY_CHARS
            ]
            if ocr_text
            else None
        ),
        "quality": quality,
        "useful": useful,
        "render_scale": (
            DISCOVERY_OCR_RENDER_SCALE
        ),
    }