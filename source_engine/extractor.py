import io

import pymupdf
import pytesseract

from PIL import Image
from pytesseract import Output


def group_ocr_words(data):
    lines = {}

    for index in range(len(data["text"])):
        text = data["text"][index].strip()

        if not text:
            continue

        block_num = data["block_num"][index]
        par_num = data["par_num"][index]
        line_num = data["line_num"][index]

        key = (
            block_num,
            par_num,
            line_num
        )

        word = {
            "text": text,
            "confidence": float(
                data["conf"][index]
            ),
            "bbox": {
                "x": int(data["left"][index]),
                "y": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index])
            }
        }

        lines.setdefault(
            key,
            []
        ).append(word)

    ocr_lines = []

    for words in lines.values():
        text = " ".join(
            word["text"]
            for word in words
        )

        confidence = sum(
            word["confidence"]
            for word in words
        ) / len(words)

        x0 = min(
            word["bbox"]["x"]
            for word in words
        )

        y0 = min(
            word["bbox"]["y"]
            for word in words
        )

        x1 = max(
            word["bbox"]["x"]
            + word["bbox"]["width"]
            for word in words
        )

        y1 = max(
            word["bbox"]["y"]
            + word["bbox"]["height"]
            for word in words
        )

        ocr_lines.append(
            {
                "text": text,
                "confidence": round(
                    confidence,
                    2
                ),
                "bbox": {
                    "x": x0,
                    "y": y0,
                    "width": x1 - x0,
                    "height": y1 - y0
                },
                "word_count": len(words)
            }
        )

    ocr_lines.sort(
        key=lambda line: (
            line["bbox"]["y"],
            line["bbox"]["x"]
        )
    )

    return ocr_lines


def group_ocr_blocks(
    ocr_lines,
    render_scale
):
    if not ocr_lines:
        return []

    blocks = []

    for line in ocr_lines:
        bbox = line["bbox"]

        current = {
            "text": line["text"],
            "confidence": line["confidence"],
            "bbox": dict(bbox),
            "lines": [line]
        }

        if not blocks:
            blocks.append(
                current
            )
            continue

        previous = blocks[-1]

        previous_bbox = previous["bbox"]

        previous_bottom = (
            previous_bbox["y"]
            + previous_bbox["height"]
        )

        current_top = bbox["y"]

        vertical_gap = (
            current_top
            - previous_bottom
        )

        previous_height = max(
            previous_bbox["height"],
            1
        )

        if vertical_gap <= previous_height * 1.8:
            previous["text"] = (
                previous["text"]
                + " "
                + line["text"]
            )

            previous["lines"].append(
                line
            )

            previous["bbox"] = {
                "x": min(
                    previous_bbox["x"],
                    bbox["x"]
                ),
                "y": min(
                    previous_bbox["y"],
                    bbox["y"]
                ),
                "width": max(
                    previous_bbox["x"]
                    + previous_bbox["width"],
                    bbox["x"]
                    + bbox["width"]
                )
                - min(
                    previous_bbox["x"],
                    bbox["x"]
                ),
                "height": max(
                    previous_bbox["y"]
                    + previous_bbox["height"],
                    bbox["y"]
                    + bbox["height"]
                )
                - min(
                    previous_bbox["y"],
                    bbox["y"]
                )
            }

            previous["confidence"] = sum(
                item["confidence"]
                for item in previous["lines"]
            ) / len(
                previous["lines"]
            )

        else:
            blocks.append(
                current
            )

    normalized_blocks = []

    for block in blocks:
        bbox = block["bbox"]

        normalized_blocks.append(
            {
                "text": block["text"],
                "confidence": round(
                    block["confidence"],
                    2
                ),
                "bbox": {
                    "x": round(
                        bbox["x"]
                        / render_scale,
                        2
                    ),
                    "y": round(
                        bbox["y"]
                        / render_scale,
                        2
                    ),
                    "width": round(
                        bbox["width"]
                        / render_scale,
                        2
                    ),
                    "height": round(
                        bbox["height"]
                        / render_scale,
                        2
                    )
                },
                "line_count": len(
                    block["lines"]
                )
            }
        )

    return normalized_blocks


def calculate_ocr_quality(
    ocr_lines,
    ocr_blocks
):
    confidences = []

    for line in ocr_lines:
        for word in line.get(
            "text",
            ""
        ).split():
            if word:
                confidences.append(
                    line["confidence"]
                )

    if not confidences:
        return {
            "score": 0.0,
            "average_confidence": 0.0,
            "low_confidence_ratio": 1.0,
            "character_count": 0,
            "block_count": 0
        }

    average_confidence = (
        sum(confidences)
        / len(confidences)
    )

    low_confidence_ratio = sum(
        1
        for confidence in confidences
        if confidence < 50
    ) / len(confidences)

    character_count = sum(
        len(line["text"])
        for line in ocr_lines
    )

    score = average_confidence

    return {
        "score": round(
            score,
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
        "block_count": len(
            ocr_blocks
        )
    }


def render_pdf_page(
    page,
    page_number
):
    native_text = page.get_text(
        "text"
    ).strip()

    drawings = page.get_drawings()

    embedded_images = page.get_images(
        full=True
    )

    visual_signals = {
        "embedded_images": len(
            embedded_images
        ),
        "drawings": len(
            drawings
        )
    }

    render_scale = 1.5

    matrix = pymupdf.Matrix(
        render_scale,
        render_scale
    )

    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    image_bytes = pixmap.tobytes(
        "png"
    )

    return {
        "page_number": page_number,
        "dimensions": {
            "width": page.rect.width,
            "height": page.rect.height,
            "unit": "pt"
        },
        "render_scale": render_scale,
        "rendered_dimensions": {
            "width": pixmap.width,
            "height": pixmap.height
        },
        "visual_signals": visual_signals,
        "native_text": native_text,
        "image_bytes": image_bytes,
        "text": native_text,
        "ocr_text": "",
        "ocr_blocks": [],
        "ocr_lines": [],
        "ocr_quality": {
            "score": 0.0,
            "average_confidence": 0.0,
            "low_confidence_ratio": 1.0,
            "character_count": 0,
            "block_count": 0
        },
        "has_text": bool(
            native_text
        ),
        "extraction_method": (
            "native"
            if native_text
            else "pending_ocr"
        )
    }


def run_ocr_on_page(
    page
):
    image = Image.open(
        io.BytesIO(
            page["image_bytes"]
        )
    )

    ocr_data = pytesseract.image_to_data(
        image,
        output_type=Output.DICT
    )

    ocr_lines = group_ocr_words(
        ocr_data
    )

    ocr_blocks = group_ocr_blocks(
        ocr_lines,
        page["render_scale"]
    )

    ocr_text = "\n".join(
        line["text"]
        for line in ocr_lines
    ).strip()

    ocr_quality = calculate_ocr_quality(
        ocr_lines,
        ocr_blocks
    )

    if page["native_text"]:
        page["text"] = page["native_text"]
        page["extraction_method"] = "native"
    else:
        page["text"] = ocr_text
        page["extraction_method"] = "ocr"

    page["ocr_text"] = ocr_text
    page["ocr_blocks"] = ocr_blocks
    page["ocr_lines"] = ocr_lines
    page["ocr_quality"] = ocr_quality
    page["has_text"] = bool(
        page["text"]
    )

    return page


def extract_pdf_page(
    page,
    page_number,
    run_ocr=True
):
    page_data = render_pdf_page(
        page,
        page_number
    )

    if run_ocr:
        return run_ocr_on_page(
            page_data
        )

    if page_data["native_text"]:
        page_data["extraction_method"] = "native"
    else:
        page_data["extraction_method"] = (
            "pending_visual_analysis"
        )

    return page_data


def iter_pdf_pages(
    file_bytes: bytes,
    run_ocr=True
):
    document = pymupdf.open(
        stream=file_bytes,
        filetype="pdf"
    )

    try:
        for index in range(
            len(document)
        ):
            page = document.load_page(
                index
            )

            yield extract_pdf_page(
                page,
                index + 1,
                run_ocr=run_ocr
            )

    finally:
        document.close()


def extract_pdf_pages(
    file_bytes: bytes,
    run_ocr=True
):
    return list(
        iter_pdf_pages(
            file_bytes,
            run_ocr=run_ocr
        )
    )




