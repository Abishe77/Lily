from source_engine.discovery.models import (
    DiscoveredUnit,
    DiscoveryResult,
)

from source_engine.discovery.pdf_discovery import (
    discover_pdf,
)

from source_engine.discovery.document_discovery import (
    source_document_to_discovery,
)

from source_engine.discovery.vision_discovery import (
    discover_image_with_vision,
)

from source_engine.docx_extractor import (
    extract_docx,
)

from source_engine.pptx_extractor import (
    extract_pptx,
)

from source_engine.txt_extractor import (
    extract_txt,
)

from source_engine.md_extractor import (
    extract_md,
)


# =========================================================
# SOURCE TYPE NORMALIZATION
# =========================================================

SOURCE_TYPE_ALIASES = {
    # Legacy database values
    "text": "txt",
    "markdown": "md",

    # Canonical values
    "txt": "txt",
    "md": "md",
    "pdf": "pdf",
    "docx": "docx",
    "pptx": "pptx",
    "image": "image",
}


def normalize_source_type(
    source_type: str,
) -> str:
    """
    Convert legacy and current source-type names into
    Lily's canonical internal source types.
    """

    if not source_type:
        raise ValueError(
            "Source type is required."
        )

    normalized = (
        str(source_type)
        .strip()
        .lower()
    )

    return SOURCE_TYPE_ALIASES.get(
        normalized,
        normalized,
    )


# =========================================================
# STANDALONE IMAGE DISCOVERY
# =========================================================

def _discover_standalone_image(
    file_bytes: bytes,
    file_name: str | None,
) -> DiscoveryResult:
    """
    Perform lightweight discovery on a standalone image.

    A standalone image is represented as one discovery unit.

    Detailed visual understanding belongs to targeted
    deep ingestion, not this discovery stage.
    """

    vision_result = discover_image_with_vision(
        file_bytes
    )

    discovery_text = vision_result.get(
        "text"
    )

    useful = bool(
        vision_result.get(
            "useful",
            False,
        )
    )

    provider = vision_result.get(
        "provider",
        "qwen",
    )

    unit = DiscoveredUnit(
        unit_index=1,
        unit_type="image",
        discovery_text=(
            discovery_text
            if useful
            else None
        ),
        discovery_metadata={
            "source_type": "image",
            "file_name": file_name,
            "provider": provider,
            "has_visual_content": True,
        },
        discovery_method=(
            "qwen_vision"
            if useful
            else "vision_unresolved"
        ),
        discovery_confidence=(
            0.80
            if useful
            else 0.0
        ),
        discovery_observed=useful,
    )

    return DiscoveryResult(
        source_type="image",
        units=[unit],
        metadata={
            "file_name": file_name,
            "unit_count": 1,
            "discovery_stage": "lightweight_vision",
            "provider": provider,
        },
    )


# =========================================================
# FORMAT-NEUTRAL DISCOVERY DISPATCHER
# =========================================================

def discover_source(
    file_bytes: bytes,
    source_type: str,
    file_name: str | None = None,
) -> DiscoveryResult:
    """
    Format-neutral source discovery entry point.

    PDF:
        native -> OCR -> Qwen Vision fallback

    DOCX / PPTX / TXT / MD:
        format extractor
            -> SourceDocument
            -> DiscoveryResult

    IMAGE:
        lightweight Qwen Vision
            -> DiscoveryResult

    This layer performs discovery only.

    It does NOT:
        - persist discovery
        - create embeddings
        - perform deep ingestion
        - create semantic chunks
        - perform retrieval
    """

    if not file_bytes:
        raise ValueError(
            "Cannot discover an empty source."
        )

    normalized_type = normalize_source_type(
        source_type
    )

    # -----------------------------------------------------
    # PDF
    # -----------------------------------------------------

    if normalized_type == "pdf":

        return discover_pdf(
            file_bytes
        )

    # -----------------------------------------------------
    # DOCX
    # -----------------------------------------------------

    if normalized_type == "docx":

        document = extract_docx(
            file_bytes=file_bytes,
            file_name=file_name,
        )

        return source_document_to_discovery(
            document
        )

    # -----------------------------------------------------
    # PPTX
    # -----------------------------------------------------

    if normalized_type == "pptx":

        document = extract_pptx(
            file_bytes=file_bytes,
            file_name=file_name,
        )

        return source_document_to_discovery(
            document
        )

    # -----------------------------------------------------
    # TXT
    # -----------------------------------------------------

    if normalized_type == "txt":

        document = extract_txt(
            file_bytes=file_bytes,
            file_name=file_name,
        )

        return source_document_to_discovery(
            document
        )

    # -----------------------------------------------------
    # MARKDOWN
    # -----------------------------------------------------

    if normalized_type == "md":

        document = extract_md(
            file_bytes=file_bytes,
            file_name=file_name,
        )

        return source_document_to_discovery(
            document
        )

    # -----------------------------------------------------
    # STANDALONE IMAGE
    # -----------------------------------------------------

    if normalized_type == "image":

        return _discover_standalone_image(
            file_bytes=file_bytes,
            file_name=file_name,
        )

    # -----------------------------------------------------
    # UNKNOWN FORMAT
    # -----------------------------------------------------

    raise ValueError(
        "Unsupported source type for discovery: "
        f"{source_type}"
    )