from source_engine.extractor import iter_pdf_pages
from source_engine.extractor import run_ocr_on_page
from source_engine.detector import detect_information_loss
from source_engine.visual_analyzer import analyze_visual_structure
from source_engine.qwen_bridge import analyze_page_with_qwen
from source_engine.normalizer import normalize_pdf_document
from source_engine.txt_extractor import extract_txt
from source_engine.md_extractor import extract_md
from source_engine.docx_extractor import extract_docx
from source_engine.pptx_extractor import extract_pptx
from source_engine.visual_router import (
    should_use_qwen,
    get_visual_blocks,
)
from source_engine.page_router import classify_page_before_ocr


def analyze_with_vision_fallback(
    image_bytes: bytes
) -> tuple[dict | None, str, str | None]:
    """
    Analyze visual content using Lily's local Qwen-VL server.

    If Qwen-VL is unavailable or fails, preserve the failure
    explicitly so the source unit can remain retryable instead
    of silently accepting low-quality OCR as authoritative
    deep knowledge.
    """

    try:
        result = analyze_page_with_qwen(
            image_bytes
        )

        return (
            result,
            "qwen",
            None,
        )

    except Exception as qwen_error:
        return (
            None,
            "failed",
            str(qwen_error),
        )


def process_pdf(
    file_bytes: bytes,
    file_name: str | None = None
) -> dict:

    processed_pages = []

    for page in iter_pdf_pages(
        file_bytes,
        run_ocr=False
    ):

        page_routing = classify_page_before_ocr(
            page
        )

        page["page_routing"] = page_routing

        qwen_visual_content = None
        vision_provider = "not_used"
        vision_error = None

        classification = page_routing["classification"]

        if classification in {"visual_first", "hybrid"}:

            visual_analysis = analyze_visual_structure(
                page
            )

            if classification == "visual_first":
                detection_reason = "visual_first_page"
            else:
                detection_reason = "hybrid_page"

            page["detection"] = {
                "needs_visual_analysis": True,
                "reason": detection_reason,
                "signals": page_routing.get(
                    "signals",
                    {}
                )
            }

            page["visual_analysis"] = visual_analysis

            (
                qwen_visual_content,
                vision_provider,
                vision_error
            ) = analyze_with_vision_fallback(
                page["image_bytes"]
            )

        else:

            page = run_ocr_on_page(
                page
            )

            detection = detect_information_loss(
                page
            )

            visual_analysis = analyze_visual_structure(
                page
            )

            page["detection"] = detection
            page["visual_analysis"] = visual_analysis

            if should_use_qwen(
                "pdf",
                page
            ):

                (
                    qwen_visual_content,
                    vision_provider,
                    vision_error
                ) = analyze_with_vision_fallback(
                    page["image_bytes"]
                )

        page_result = {
            "page_number": page["page_number"],
            "dimensions": page["dimensions"],
            "render_scale": page["render_scale"],
            "rendered_dimensions": page["rendered_dimensions"],
            "visual_signals": page["visual_signals"],
            "text": page["text"],
            "native_text": page["native_text"],
            "ocr_text": page["ocr_text"],
            "ocr_blocks": page["ocr_blocks"],
            "ocr_lines": page["ocr_lines"],
            "ocr_quality": page["ocr_quality"],
            "extraction_method": page["extraction_method"],
            "page_routing": page["page_routing"],
            "detection": page["detection"],
            "visual_analysis": page["visual_analysis"],
            "qwen_visual_content": qwen_visual_content,
            "vision_provider": vision_provider,
            "vision_error": vision_error
        }

        processed_pages.append(
            page_result
        )

    return normalize_pdf_document(
        processed_pages,
        file_name=file_name
    )


def process_txt(
    file_bytes: bytes,
    file_name: str | None = None
) -> dict:

    return extract_txt(
        file_bytes,
        file_name=file_name
    )


def process_md(
    file_bytes: bytes,
    file_name: str | None = None
) -> dict:

    return extract_md(
        file_bytes,
        file_name=file_name
    )


def process_docx(
    file_bytes: bytes,
    file_name: str | None = None
) -> dict:

    document = extract_docx(
        file_bytes,
        file_name=file_name
    )

    for page in document["pages"]:

        visual_blocks = get_visual_blocks(
            "docx",
            page
        )

        for block in visual_blocks:

            content = block.get(
                "content",
                {}
            )

            if not isinstance(
                content,
                dict
            ):
                continue

            image_bytes = content.get(
                "image_bytes"
            )

            if not image_bytes:
                continue

            (
                visual_content,
                provider,
                error
            ) = analyze_with_vision_fallback(
                image_bytes
            )

            block["visual_analysis"] = visual_content
            block["vision_provider"] = provider
            block["vision_error"] = error

            block["content"] = {
                "mime_type": content.get(
                    "mime_type"
                ),
                "size_bytes": content.get(
                    "size_bytes"
                )
            }

    return document


def process_pptx(
    file_bytes: bytes,
    file_name: str | None = None
) -> dict:

    document = extract_pptx(
        file_bytes,
        file_name=file_name
    )

    for page in document["pages"]:

        if not should_use_qwen(
            "pptx",
            page
        ):
            continue

        for block in page["content_blocks"]:

            if block["type"] != "image":
                continue

            image_bytes = block["content"].get(
                "image_bytes"
            )

            if not image_bytes:
                continue

            (
                visual_content,
                provider,
                error
            ) = analyze_with_vision_fallback(
                image_bytes
            )

            block["visual_analysis"] = visual_content
            block["vision_provider"] = provider
            block["vision_error"] = error

            block["content"] = {
                "mime_type": block["content"].get(
                    "mime_type"
                ),
                "size_bytes": block["content"].get(
                    "size_bytes"
                )
            }

    return document


def process_source(
    file_bytes: bytes,
    file_name: str
) -> dict:

    extension = file_name.lower().rsplit(
        ".",
        1
    )[-1]

    if extension == "pdf":

        return process_pdf(
            file_bytes,
            file_name
        )

    if extension == "txt":

        return process_txt(
            file_bytes,
            file_name
        )

    if extension == "md":

        return process_md(
            file_bytes,
            file_name
        )

    if extension == "docx":

        return process_docx(
            file_bytes,
            file_name
        )

    if extension == "pptx":

        return process_pptx(
            file_bytes,
            file_name
        )

    raise ValueError(
        f"Unsupported source type: .{extension}"
    )






