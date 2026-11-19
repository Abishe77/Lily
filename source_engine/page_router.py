from PIL import Image
import io


def calculate_visual_density(
    image_bytes: bytes
) -> dict:

    image = Image.open(
        io.BytesIO(
            image_bytes
        )
    ).convert(
        "L"
    )

    width, height = image.size

    if width == 0 or height == 0:

        return {
            "image_width": width,
            "image_height": height,
            "dark_pixel_ratio": 0.0
        }

    thumbnail = image.copy()

    thumbnail.thumbnail(
        (800, 800)
    )

    pixels = list(
        thumbnail.getdata()
    )

    dark_pixels = sum(
        1
        for pixel in pixels
        if pixel < 180
    )

    dark_pixel_ratio = (
        dark_pixels
        / len(pixels)
    )

    return {
        "image_width": width,
        "image_height": height,
        "dark_pixel_ratio": round(
            dark_pixel_ratio,
            4
        )
    }


def classify_page_before_ocr(
    page: dict
) -> dict:

    native_text = page.get(
        "native_text",
        ""
    ).strip()

    image_bytes = page.get(
        "image_bytes"
    )

    visual_signals = page.get(
        "visual_signals",
        {}
    )

    embedded_images = visual_signals.get(
        "embedded_images",
        0
    )

    drawings = visual_signals.get(
        "drawings",
        0
    )

    native_text_available = bool(
        native_text
    )

    has_visual_content = (
        embedded_images > 0
        or drawings > 0
    )

    if (
        native_text_available
        and has_visual_content
    ):

        return {
            "classification": "hybrid",
            "confidence": "high",
            "reason": "native_text_with_visual_content",
            "signals": {
                "native_text_available": True,
                "native_text_length": len(
                    native_text
                ),
                "embedded_images": embedded_images,
                "drawings": drawings
            }
        }

    if native_text_available:

        return {
            "classification": "text_first",
            "confidence": "high",
            "reason": "native_text_available",
            "signals": {
                "native_text_available": True,
                "native_text_length": len(
                    native_text
                ),
                "embedded_images": embedded_images,
                "drawings": drawings
            }
        }

    if not image_bytes:

        return {
            "classification": "unknown",
            "confidence": "low",
            "reason": "page_image_unavailable",
            "signals": {
                "native_text_available": False,
                "embedded_images": embedded_images,
                "drawings": drawings
            }
        }

    visual_density = calculate_visual_density(
        image_bytes
    )

    dark_pixel_ratio = visual_density[
        "dark_pixel_ratio"
    ]

    if (
        embedded_images > 0
        and dark_pixel_ratio < 0.18
    ):

        return {
            "classification": "visual_first",
            "confidence": "medium",
            "reason": "image_heavy_page_without_native_text",
            "signals": {
                "native_text_available": False,
                "embedded_images": embedded_images,
                "drawings": drawings,
                "dark_pixel_ratio": dark_pixel_ratio
            }
        }

    if (
        drawings > 0
        and dark_pixel_ratio < 0.18
    ):

        return {
            "classification": "visual_first",
            "confidence": "medium",
            "reason": "drawing_heavy_page_without_native_text",
            "signals": {
                "native_text_available": False,
                "embedded_images": embedded_images,
                "drawings": drawings,
                "dark_pixel_ratio": dark_pixel_ratio
            }
        }

    return {
        "classification": "unknown",
        "confidence": "low",
        "reason": "insufficient_pre_ocr_evidence",
        "signals": {
            "native_text_available": False,
            "embedded_images": embedded_images,
            "drawings": drawings,
            "dark_pixel_ratio": dark_pixel_ratio
        }
    }