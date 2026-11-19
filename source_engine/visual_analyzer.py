
import cv2
import numpy as np


def normalize_bbox(
    bbox: dict,
    page_dimensions: dict,
    rendered_dimensions: dict
) -> dict:

    scale_x = (
        page_dimensions["width"]
        / rendered_dimensions["width"]
    )

    scale_y = (
        page_dimensions["height"]
        / rendered_dimensions["height"]
    )

    return {
        "x": bbox["x"] * scale_x,
        "y": bbox["y"] * scale_y,
        "width": bbox["width"] * scale_x,
        "height": bbox["height"] * scale_y
    }


def calculate_vertical_gaps(
    lines: list
) -> list:

    gaps = []

    for i in range(len(lines) - 1):

        current_line = lines[i]
        next_line = lines[i + 1]

        current_bbox = current_line["bbox"]
        next_bbox = next_line["bbox"]

        current_bottom = (
            current_bbox["y"]
            + current_bbox["height"]
        )

        gap = (
            next_bbox["y"]
            - current_bottom
        )

        gaps.append({
            "after_line": i + 1,
            "before_line": i + 2,
            "gap": gap
        })

    return gaps


def detect_large_vertical_gaps(
    vertical_gaps: list,
    threshold: float = 15.0
) -> list:

    large_gaps = []

    for gap in vertical_gaps:

        if gap["gap"] > threshold:

            large_gaps.append({
                "after_line": gap["after_line"],
                "before_line": gap["before_line"],
                "gap": gap["gap"]
            })

    return large_gaps


def calculate_vertical_overlap(
    bbox_a: dict,
    bbox_b: dict
) -> float:

    top = max(
        bbox_a["y"],
        bbox_b["y"]
    )

    bottom = min(
        bbox_a["y"] + bbox_a["height"],
        bbox_b["y"] + bbox_b["height"]
    )

    overlap = max(
        0.0,
        bottom - top
    )

    smaller_height = min(
        bbox_a["height"],
        bbox_b["height"]
    )

    if smaller_height <= 0:
        return 0.0

    return overlap / smaller_height


def calculate_horizontal_gap(
    bbox_a: dict,
    bbox_b: dict
) -> float:

    right_a = (
        bbox_a["x"]
        + bbox_a["width"]
    )

    right_b = (
        bbox_b["x"]
        + bbox_b["width"]
    )

    if bbox_a["x"] <= bbox_b["x"]:
        return bbox_b["x"] - right_a

    return bbox_a["x"] - right_b


def detect_side_by_side_regions(
    lines: list,
    minimum_vertical_overlap: float = 0.5,
    minimum_horizontal_gap: float = 15.0
) -> list:

    regions = []

    for i in range(len(lines)):

        for j in range(i + 1, len(lines)):

            first = lines[i]
            second = lines[j]

            first_bbox = first["bbox"]
            second_bbox = second["bbox"]

            vertical_overlap = calculate_vertical_overlap(
                first_bbox,
                second_bbox
            )

            if vertical_overlap < minimum_vertical_overlap:
                continue

            horizontal_gap = calculate_horizontal_gap(
                first_bbox,
                second_bbox
            )

            if horizontal_gap < minimum_horizontal_gap:
                continue

            if first_bbox["x"] < second_bbox["x"]:
                left_line = i + 1
                right_line = j + 1
            else:
                left_line = j + 1
                right_line = i + 1

            regions.append({
                "left_line": left_line,
                "right_line": right_line,
                "horizontal_gap": horizontal_gap,
                "vertical_overlap": vertical_overlap
            })

    return regions


def detect_visual_regions(
    image_bytes: bytes,
    page_dimensions: dict
) -> list:

    image_array = np.frombuffer(
        image_bytes,
        dtype=np.uint8
    )

    image = cv2.imdecode(
        image_array,
        cv2.IMREAD_GRAYSCALE
    )

    if image is None:
        return []

    blurred = cv2.GaussianBlur(
        image,
        (5, 5),
        0
    )

    thresholded = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (15, 15)
    )

    connected = cv2.morphologyEx(
        thresholded,
        cv2.MORPH_CLOSE,
        kernel
    )

    contours = cv2.findContours(
        connected,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )[0]

    image_height, image_width = image.shape

    page_width = page_dimensions["width"]
    page_height = page_dimensions["height"]

    scale_x = page_width / image_width
    scale_y = page_height / image_height

    page_area = image_width * image_height

    regions = []

    for contour in contours:

        x, y, width, height = cv2.boundingRect(
            contour
        )

        area = width * height

        if area < page_area * 0.01:
            continue

        regions.append({
            "x": x * scale_x,
            "y": y * scale_y,
            "width": width * scale_x,
            "height": height * scale_y,
            "area_ratio": area / page_area
        })

    regions.sort(
        key=lambda region: region["area_ratio"],
        reverse=True
    )

    return regions


def analyze_visual_structure(
    page_data: dict
) -> dict:

    visual_signals = page_data.get(
        "visual_signals",
        {}
    )

    signals = []

    if visual_signals.get(
        "has_images",
        False
    ):
        signals.append(
            "embedded_images"
        )

    if visual_signals.get(
        "has_drawings",
        False
    ):
        signals.append(
            "vector_drawings"
        )

    normalized_lines = []

    page_dimensions = page_data.get(
        "dimensions"
    )

    rendered_dimensions = page_data.get(
        "rendered_dimensions"
    )

    if page_dimensions and rendered_dimensions:

        for line in page_data.get(
            "ocr_lines",
            []
        ):

            normalized_bbox = normalize_bbox(
                line["bbox"],
                page_dimensions,
                rendered_dimensions
            )

            normalized_lines.append({
                "text": line["text"],
                "bbox": normalized_bbox,
                "confidence": line["confidence"],
                "word_count": line["word_count"]
            })

    vertical_gaps = calculate_vertical_gaps(
        normalized_lines
    )

    large_vertical_gaps = detect_large_vertical_gaps(
        vertical_gaps
    )

    side_by_side_regions = detect_side_by_side_regions(
        normalized_lines
    )

    visual_regions = []

    if page_dimensions and page_data.get(
        "image_bytes"
    ):
        visual_regions = detect_visual_regions(
            page_data["image_bytes"],
            page_dimensions
        )

    if large_vertical_gaps:
        signals.append(
            "large_vertical_gaps"
        )

    if side_by_side_regions:
        signals.append(
            "side_by_side_regions"
        )

    if visual_regions:
        signals.append(
            "visual_regions"
        )

    return {
        "needs_visual_analysis": bool(signals),
        "signals": signals,
        "signal_count": len(signals),
        "normalized_ocr_lines": normalized_lines,
        "vertical_gaps": vertical_gaps,
        "large_vertical_gaps": large_vertical_gaps,
        "side_by_side_regions": side_by_side_regions,
        "visual_regions": visual_regions
    }





