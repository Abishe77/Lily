from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
import json
import pymupdf

from source_engine.ingestion.canonical_ingestion import (
    
    build_native_canonical_content,
    build_retrieval_text,
)
from source_engine.ingestion.semantic_chunking import semantic_chunk_text
from source_engine.ingestion.chunk_persistence import store_source_chunks
from source_engine.storage.source_storage import read_source_file
from source_engine.docx_extractor import extract_docx
from source_engine.pptx_extractor import extract_pptx
from source_engine.qwen_vision import extract_visual_content


def _parse_discovery_metadata(
    value,
) -> dict:
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    return {}


def _get_pdf_visual_text_for_unit(
    cur,
    source_id: int,
    unit_index: int,
) -> str:
    cur.execute(
        """
        SELECT
            storage_key
        FROM sources
        WHERE id = %s
          AND source_type = 'pdf';
        """,
        (source_id,),
    )

    row = cur.fetchone()

    if row is None:
        raise ValueError(
            f"PDF source {source_id} not found."
        )

    storage_key = row[0]

    file_bytes = read_source_file(
        storage_key
    )

    document = pymupdf.open(
        stream=file_bytes,
        filetype="pdf",
    )

    try:
        page_index = unit_index - 1

        if (
            page_index < 0
            or page_index >= document.page_count
        ):
            raise ValueError(
                f"Page {unit_index} does not exist "
                f"in PDF source {source_id}."
            )

        page = document.load_page(
            page_index
        )

        matrix = pymupdf.Matrix(
            2.0,
            2.0,
        )

        pixmap = page.get_pixmap(
            matrix=matrix,
            alpha=False,
        )

        image_bytes = pixmap.tobytes(
            "png"
        )

        result = _run_qwen_on_visual_asset(
            {
                "image_bytes": image_bytes,
                "mime_type": "image/png",
            }
        )

        if not isinstance(
            result,
            dict,
        ):
            return ""

        return (
            _qwen_result_to_retrieval_text(
                result
            )
        ).strip()

    finally:
        document.close()


def _load_source_visual_document(
    cur,
    source_id: int,
) -> tuple[str, str, dict]:
    cur.execute(
        """
        SELECT
            source_type,
            filename,
            storage_key
        FROM sources
        WHERE id = %s;
        """,
        (source_id,),
    )

    row = cur.fetchone()

    if row is None:
        raise ValueError(
            f"Source {source_id} not found."
        )

    source_type, file_name, storage_key = row

    if source_type not in {"docx", "pptx"}:
        raise ValueError(
            f"Visual reconstruction is not supported for "
            f"source type '{source_type}'."
        )

    file_bytes = read_source_file(
        storage_key
    )

    if source_type == "docx":
        source_document = extract_docx(
            file_bytes=file_bytes,
            file_name=file_name,
        )

    elif source_type == "pptx":
        source_document = extract_pptx(
            file_bytes=file_bytes,
            file_name=file_name,
        )

    else:
        raise ValueError(
            f"Unsupported visual source type: {source_type}"
        )

    return (
        source_type,
        file_name,
        source_document,
    )


def _get_source_page(
    source_document: dict,
    unit_index: int,
) -> dict | None:
    for page in source_document.get(
        "pages",
        [],
    ):
        if page.get(
            "page_number"
        ) == unit_index:
            return page

    return None


def _collect_visual_assets(
    page: dict,
) -> list[dict]:
    assets = []
    seen_hashes = set()

    for block in page.get(
        "content_blocks",
        [],
    ):
        block_type = block.get(
            "type"
        )

        content = block.get(
            "content"
        )

        if block_type == "image":
            if not isinstance(
                content,
                dict,
            ):
                continue

            image_bytes = content.get(
                "image_bytes"
            )

            if not image_bytes:
                continue

            image_hash = sha256(
                image_bytes
            ).hexdigest()

            if image_hash in seen_hashes:
                continue

            seen_hashes.add(
                image_hash
            )

            assets.append(
                {
                    "image_bytes": image_bytes,
                    "mime_type": content.get(
                        "mime_type",
                        "application/octet-stream",
                    ),
                    "block_id": block.get(
                        "block_id"
                    ),
                    "block_type": "image",
                    "provenance": block.get(
                        "provenance",
                        {},
                    ),
                    "location": block.get(
                        "location",
                        {},
                    ),
                }
            )

        elif block_type == "diagram":
            if not isinstance(
                content,
                dict,
            ):
                continue

            image_assets = content.get(
                "image_assets",
                [],
            )

            if not isinstance(
                image_assets,
                list,
            ):
                continue

            for image in image_assets:
                if not isinstance(
                    image,
                    dict,
                ):
                    continue

                image_bytes = image.get(
                    "image_bytes"
                )

                if not image_bytes:
                    continue

                image_hash = sha256(
                    image_bytes
                ).hexdigest()

                if image_hash in seen_hashes:
                    continue

                seen_hashes.add(
                    image_hash
                )

                assets.append(
                    {
                        "image_bytes": image_bytes,
                        "mime_type": image.get(
                            "mime_type",
                            "application/octet-stream",
                        ),
                        "block_id": block.get(
                            "block_id"
                        ),
                        "block_type": "diagram_image",
                        "provenance": {
                            **block.get(
                                "provenance",
                                {},
                            ),
                            "archive_path": image.get(
                                "archive_path"
                            ),
                            "relationship_id": image.get(
                                "relationship_id"
                            ),
                        },
                        "location": block.get(
                            "location",
                            {},
                        ),
                    }
                )

    return assets


def _qwen_result_to_retrieval_text(
    result: dict,
) -> str:
    parts = []

    def add_section(
        title: str,
        value,
    ) -> None:
        if value is None:
            return

        if isinstance(
            value,
            str,
        ):
            value = value.strip()

            if value:
                parts.append(
                    f"{title}: {value}"
                )

            return

        if isinstance(
            value,
            list,
        ):
            cleaned = []

            for item in value:
                if isinstance(
                    item,
                    str,
                ):
                    item = item.strip()

                    if item:
                        cleaned.append(
                            item
                        )

                elif isinstance(
                    item,
                    dict,
                ):
                    fields = []

                    for key, val in item.items():
                        if val is None:
                            continue

                        if isinstance(
                            val,
                            (
                                str,
                                int,
                                float,
                                bool,
                            ),
                        ):
                            fields.append(
                                f"{key}: {val}"
                            )

                    if fields:
                        cleaned.append(
                            "; ".join(
                                fields
                            )
                        )

            if cleaned:
                parts.append(
                    f"{title}: "
                    + " | ".join(
                        cleaned
                    )
                )

            return

        if isinstance(
            value,
            dict,
        ):
            fields = []

            for key, val in value.items():
                if val is None:
                    continue

                if isinstance(
                    val,
                    (
                        str,
                        int,
                        float,
                        bool,
                    ),
                ):
                    text = str(
                        val
                    ).strip()

                    if text:
                        fields.append(
                            f"{key}: {text}"
                        )

            if fields:
                parts.append(
                    f"{title}: "
                    + "; ".join(
                        fields
                    )
                )

    add_section(
        "Visible text",
        result.get(
            "visible_text"
        ),
    )

    add_section(
        "Visual content",
        result.get(
            "visual_content"
        ),
    )

    add_section(
        "Diagrams",
        result.get(
            "diagrams"
        ),
    )

    add_section(
        "Charts or graphs",
        result.get(
            "charts_or_graphs"
        ),
    )

    add_section(
        "Tables",
        result.get(
            "tables"
        ),
    )

    add_section(
        "Equations or formulas",
        result.get(
            "equations_or_formulas"
        ),
    )

    add_section(
        "Important visual information",
        result.get(
            "important_visual_information"
        ),
    )

    add_section(
        "Extraction notes",
        result.get(
            "extraction_notes"
        ),
    )

    return "\n".join(
        parts
    ).strip()


def _run_qwen_on_visual_asset(
    asset: dict,
) -> dict | None:
    image_bytes = asset.get(
        "image_bytes"
    )

    if not image_bytes:
        return None

    suffix = ".png"

    mime_type = (
        asset.get(
            "mime_type"
        )
        or ""
    ).lower()

    if (
        "jpeg" in mime_type
        or "jpg" in mime_type
    ):
        suffix = ".jpg"

    elif "webp" in mime_type:
        suffix = ".webp"

    elif "gif" in mime_type:
        suffix = ".gif"

    elif "bmp" in mime_type:
        suffix = ".bmp"

    elif "tiff" in mime_type:
        suffix = ".tiff"

    temporary_path = None

    try:
        with NamedTemporaryFile(
            suffix=suffix,
            delete=False,
        ) as temp_file:
            temp_file.write(
                image_bytes
            )

            temporary_path = Path(
                temp_file.name
            )

        result = extract_visual_content(
            temporary_path
        )

        if not isinstance(
            result,
            dict,
        ):
            return None

        return result

    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            temporary_path.unlink()


def _build_visual_retrieval_text_for_unit(
    page: dict,
) -> str:
    assets = _collect_visual_assets(
        page
    )

    if not assets:
        return ""

    visual_parts = []

    for index, asset in enumerate(
        assets,
        start=1,
    ):
        result = _run_qwen_on_visual_asset(
            asset
        )

        if not result:
            continue

        visual_text = (
            _qwen_result_to_retrieval_text(
                result
            )
        )

        if not visual_text:
            continue

        visual_parts.append(
            (
                f"Visual asset {index}\n"
                f"{visual_text}"
            )
        )

    return "\n\n".join(
        visual_parts
    ).strip()


def _build_unit_retrieval_text(
    discovery_text: str,
    unit_index: int,
    unit_type: str,
    visual_retrieval_text: str = "",
) -> str:
    canonical_content = (
        build_native_canonical_content(
            discovery_text=discovery_text,
            unit_index=unit_index,
            unit_type=unit_type,
        )
    )

    retrieval_text = (
        build_retrieval_text(
            canonical_content
        )
    )

    if visual_retrieval_text.strip():
        if retrieval_text.strip():
            retrieval_text = (
                retrieval_text.strip()
                + "\n\n"
                + visual_retrieval_text.strip()
            )

        else:
            retrieval_text = (
                visual_retrieval_text.strip()
            )

    return retrieval_text.strip()


def _prepare_visual_document(
    cur,
    source_id: int,
    cache: dict,
) -> dict | None:
    if cache.get(
        "loaded"
    ):
        return cache.get(
            "source_document"
        )

    try:
        (
            source_type,
            file_name,
            source_document,
        ) = _load_source_visual_document(
            cur=cur,
            source_id=source_id,
        )

    except ValueError:
        cache[
            "loaded"
        ] = True

        cache[
            "source_document"
        ] = None

        return None

    cache[
        "loaded"
    ] = True

    cache[
        "source_type"
    ] = source_type

    cache[
        "file_name"
    ] = file_name

    cache[
        "source_document"
    ] = source_document

    return source_document


def _get_visual_text_for_unit(
    cur,
    source_id: int,
    unit_index: int,
    visual_cache: dict,
) -> str:
    source_document = (
        _prepare_visual_document(
            cur=cur,
            source_id=source_id,
            cache=visual_cache,
        )
    )

    if source_document is None:
        return ""

    page = _get_source_page(
        source_document=source_document,
        unit_index=unit_index,
    )

    if page is None:
        return ""

    return (
        _build_visual_retrieval_text_for_unit(
            page
        )
    )


def ingest_source_units(
    cur,
    source_id: int,
) -> dict:
    cur.execute(
        """
        SELECT
            id,
            unit_index,
            unit_type,
            discovery_text
        FROM source_units
        WHERE source_id = %s
          AND status IN ('discovered', 'ingested')
          AND discovery_text IS NOT NULL
          AND TRIM(discovery_text) <> ''
        ORDER BY unit_index;
        """,
        (source_id,),
    )

    units = cur.fetchall()

    if not units:
        return {
            "source_id": source_id,
            "units_processed": 0,
            "chunks_created": 0,
            "visual_assets_processed": 0,
        }

    units_processed = 0
    chunks_created = 0
    visual_assets_processed = 0

    visual_cache = {
        "loaded": False,
        "source_document": None,
        "source_type": None,
        "file_name": None,
    }

    for (
        unit_id,
        unit_index,
        unit_type,
        discovery_text,
    ) in units:
        canonical_content = (
            build_native_canonical_content(
                discovery_text=discovery_text,
                unit_index=unit_index,
                unit_type=unit_type,
            )
        )

        retrieval_text = (
            build_retrieval_text(
                canonical_content
            )
        )

        visual_retrieval_text = ""

        try:
            visual_retrieval_text = (
                _get_visual_text_for_unit(
                    cur=cur,
                    source_id=source_id,
                    unit_index=unit_index,
                    visual_cache=visual_cache,
                )
            )

            if visual_retrieval_text:
                visual_assets_processed += (
                    visual_retrieval_text.count(
                        "Visual asset "
                    )
                )

        except Exception as exc:
            print(
                f"[source-ingestion] "
                f"Qwen visual ingestion failed "
                f"for source={source_id}, "
                f"unit={unit_index}: {exc}"
            )

        if visual_retrieval_text:
            retrieval_text = (
                retrieval_text.strip()
                + "\n\n"
                + visual_retrieval_text.strip()
            ).strip()

        if not retrieval_text:
            continue

        chunks = semantic_chunk_text(
            retrieval_text
        )

        if not chunks:
            continue

        stored_count = store_source_chunks(
            cur=cur,
            source_unit_id=unit_id,
            chunks=chunks,
        )

        if stored_count <= 0:
            continue

        chunks_created += stored_count
        units_processed += 1

        now = datetime.now(
            timezone.utc
        )

        cur.execute(
            """
            UPDATE source_units
            SET
                status = 'ingested',
                ingested_at = %s,
                updated_at = %s
            WHERE id = %s;
            """,
            (
                now,
                now,
                unit_id,
            ),
        )

    return {
        "source_id": source_id,
        "units_processed": units_processed,
        "chunks_created": chunks_created,
        "visual_assets_processed": visual_assets_processed,
    }


def ingest_targeted_source_units(
    cur,
    source_id: int,
    unit_ids: list[int],
) -> dict:
    if not unit_ids:
        return {
            "source_id": source_id,
            "requested_units": 0,
            "units_processed": 0,
            "chunks_created": 0,
            "visual_assets_processed": 0,
        }

    cur.execute(
        """
        SELECT
            id,
            unit_index,
            unit_type,
            discovery_text,
            discovery_metadata
        FROM source_units
        WHERE source_id = %s
          AND id = ANY(%s)
          AND status != 'ingested'
        ORDER BY unit_index;
        """,
        (
            source_id,
            unit_ids,
        ),
    )

    units = cur.fetchall()

    units_processed = 0
    chunks_created = 0
    visual_assets_processed = 0

    visual_cache = {
        "loaded": False,
        "source_document": None,
        "source_type": None,
        "file_name": None,
    }

    for (
        unit_id,
        unit_index,
        unit_type,
        discovery_text,
        discovery_metadata,
    ) in units:
        metadata = _parse_discovery_metadata(
            discovery_metadata
        )

        requires_vision = bool(
            metadata.get(
                "requires_vision",
                False,
            )
        )

        if requires_vision:
            try:
                retrieval_text = (
                    _get_pdf_visual_text_for_unit(
                        cur=cur,
                        source_id=source_id,
                        unit_index=unit_index,
                    )
                )

            except Exception as exc:
                print(
                    f"[source-ingestion] "
                    f"Required PDF vision failed "
                    f"for source={source_id}, "
                    f"unit={unit_index}: {exc}"
                )

                continue

            if not retrieval_text:
                print(
                    f"[source-ingestion] "
                    f"Required PDF vision returned no "
                    f"usable content for source={source_id}, "
                    f"unit={unit_index}"
                )

                continue

            visual_assets_processed += 1

        else:
            if not discovery_text:
                continue

            canonical_content = (
                build_native_canonical_content(
                    discovery_text=discovery_text,
                    unit_index=unit_index,
                    unit_type=unit_type,
                )
            )

            retrieval_text = (
                build_retrieval_text(
                    canonical_content
                )
            )

            visual_retrieval_text = ""

            try:
                visual_retrieval_text = (
                    _get_visual_text_for_unit(
                        cur=cur,
                        source_id=source_id,
                        unit_index=unit_index,
                        visual_cache=visual_cache,
                    )
                )

                if visual_retrieval_text:
                    visual_assets_processed += (
                        visual_retrieval_text.count(
                            "Visual asset "
                        )
                    )

            except Exception as exc:
                print(
                    f"[source-ingestion] "
                    f"Qwen visual ingestion failed "
                    f"for source={source_id}, "
                    f"unit={unit_index}: {exc}"
                )

            if visual_retrieval_text:
                if retrieval_text:
                    retrieval_text = (
                        retrieval_text.strip()
                        + "\n\n"
                        + visual_retrieval_text.strip()
                    )

                else:
                    retrieval_text = (
                        visual_retrieval_text.strip()
                    )

        retrieval_text = (
            retrieval_text.strip()
        )

        if not retrieval_text:
            continue

        chunks = semantic_chunk_text(
            retrieval_text
        )

        if not chunks:
            continue

        stored_count = store_source_chunks(
            cur=cur,
            source_unit_id=unit_id,
            chunks=chunks,
        )

        if stored_count <= 0:
            continue

        chunks_created += stored_count
        units_processed += 1

        now = datetime.now(
            timezone.utc
        )

        cur.execute(
            """
            UPDATE source_units
            SET
                status = 'ingested',
                ingested_at = %s,
                updated_at = %s
            WHERE id = %s;
            """,
            (
                now,
                now,
                unit_id,
            ),
        )

    return {
        "source_id": source_id,
        "requested_units": len(
            unit_ids
        ),
        "units_processed": units_processed,
        "chunks_created": chunks_created,
        "visual_assets_processed": visual_assets_processed,
    }