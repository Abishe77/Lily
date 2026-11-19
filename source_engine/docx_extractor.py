from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from docx import Document

from source_engine.source_model import (
    create_content_block,
    create_page,
    create_source_document,
)


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


DOCUMENT_XML = "word/document.xml"
RELATIONSHIPS_XML = "word/_rels/document.xml.rels"


def _extract_text(element) -> str:
    parts = []

    for text_node in element.iter():
        if text_node.tag.endswith("}t"):
            if text_node.text:
                parts.append(text_node.text)

    return " ".join("".join(parts).split())


def _get_attr(element, namespace: str, name: str):
    return element.get(f"{{{namespace}}}{name}")


def _get_doc_properties(element) -> dict:
    for child in element.iter():
        if child.tag.endswith("}docPr"):
            return {
                "id": child.get("id"),
                "name": child.get("name"),
                "description": child.get("descr"),
                "title": child.get("title"),
            }

    return {}


def _get_extent(element) -> dict:
    for child in element.iter():
        if child.tag.endswith("}extent"):
            try:
                return {
                    "cx": int(child.get("cx", 0)),
                    "cy": int(child.get("cy", 0)),
                }
            except ValueError:
                return {}

    return {}


def _get_position(element) -> dict:
    position = {}

    for child in element.iter():

        if child.tag.endswith("}positionH"):

            position["horizontal_relative_from"] = child.get(
                "relativeFrom"
            )

            for subchild in child:
                if subchild.tag.endswith("}posOffset"):
                    if subchild.text:
                        position["horizontal_offset"] = int(
                            subchild.text
                        )

        elif child.tag.endswith("}positionV"):

            position["vertical_relative_from"] = child.get(
                "relativeFrom"
            )

            for subchild in child:
                if subchild.tag.endswith("}posOffset"):
                    if subchild.text:
                        position["vertical_offset"] = int(
                            subchild.text
                        )

    return position


def _load_relationships(zip_file: ZipFile) -> dict:

    if RELATIONSHIPS_XML not in zip_file.namelist():
        return {}

    root = ET.fromstring(
        zip_file.read(RELATIONSHIPS_XML)
    )

    relationships = {}

    for relationship in root:

        relationship_id = relationship.get("Id")
        target = relationship.get("Target")

        if relationship_id and target:
            relationships[relationship_id] = target

    return relationships


def _resolve_media_target(target: str) -> str:

    target = target.replace("\\", "/")

    if target.startswith("/"):
        return target.lstrip("/")

    return str(
        PurePosixPath("word") / PurePosixPath(target)
    )


def _guess_mime_type(path: str) -> str:

    suffix = PurePosixPath(path).suffix.lower()

    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }

    return mapping.get(
        suffix,
        "application/octet-stream"
    )


def _extract_images(
    element,
    zip_file: ZipFile,
    relationships: dict,
    image_cache: dict,
) -> list[dict]:

    images = []

    for node in element.iter():

        if not node.tag.endswith("}blip"):
            continue

        relationship_id = _get_attr(
            node,
            NS["r"],
            "embed",
        )

        if not relationship_id:
            continue

        target = relationships.get(
            relationship_id
        )

        if not target:
            continue

        archive_path = _resolve_media_target(
            target
        )

        if archive_path not in zip_file.namelist():
            continue

        if archive_path not in image_cache:

            image_cache[archive_path] = zip_file.read(
                archive_path
            )

        image_bytes = image_cache[
            archive_path
        ]

        images.append({
            "relationship_id": relationship_id,
            "target": target,
            "archive_path": archive_path,
            "mime_type": _guess_mime_type(
                archive_path
            ),
            "size_bytes": len(image_bytes),
            "image_bytes": image_bytes,
        })

    return images


def _extract_shape(element) -> dict:

    properties = _get_doc_properties(
        element
    )

    return {
        "type": "shape",
        "name": properties.get("name"),
        "id": properties.get("id"),
        "text": _extract_text(element),
        "extent": _get_extent(element),
        "position": {},
        "images": [],
    }


def _extract_picture(
    element,
    zip_file: ZipFile,
    relationships: dict,
    image_cache: dict,
) -> dict:

    properties = _get_doc_properties(
        element
    )

    images = _extract_images(
        element,
        zip_file,
        relationships,
        image_cache,
    )

    return {
        "type": "picture",
        "name": properties.get("name"),
        "id": properties.get("id"),
        "text": _extract_text(element),
        "extent": _get_extent(element),
        "position": {},
        "images": images,
    }


def _extract_group(
    group,
    zip_file: ZipFile,
    relationships: dict,
    image_cache: dict,
) -> dict:

    children = []

    for child in list(group):

        if child.tag.endswith("}wgp"):

            children.append(
                _extract_group(
                    child,
                    zip_file,
                    relationships,
                    image_cache,
                )
            )

        elif child.tag.endswith("}wsp"):

            children.append(
                _extract_shape(child)
            )

        elif child.tag.endswith("}pic"):

            children.append(
                _extract_picture(
                    child,
                    zip_file,
                    relationships,
                    image_cache,
                )
            )

    return {
        "type": "group",
        "text": _extract_text(group),
        "extent": {},
        "position": {},
        "children": children,
    }


def _extract_drawing(
    drawing,
    zip_file: ZipFile,
    relationships: dict,
    image_cache: dict,
) -> dict | None:

    inline = None
    anchor = None

    for child in list(drawing):

        if child.tag.endswith("}inline"):
            inline = child

        elif child.tag.endswith("}anchor"):
            anchor = child

    container = anchor or inline

    if container is None:
        return None

    properties = _get_doc_properties(
        container
    )

    extent = _get_extent(
        container
    )

    position = _get_position(
        container
    )

    container_name = (
        "anchor"
        if anchor is not None
        else "inline"
    )

    # ---------------------------------------------------------
    # DrawingML objects are nested inside:
    #
    # anchor/inline
    #   -> graphic
    #       -> graphicData
    #           -> wpg:wgp
    #           -> wps:wsp
    #           -> pic:pic
    #
    # Therefore search descendants rather than only
    # direct children.
    # ---------------------------------------------------------

    group = None
    shape = None
    picture = None

    for node in container.iter():

        if node is container:
            continue

        if node.tag.endswith("}wgp"):
            group = node
            break

        if node.tag.endswith("}wsp"):
            shape = node
            break

        if node.tag.endswith("}pic"):
            picture = node
            break

    if group is not None:

        result = _extract_group(
            group,
            zip_file,
            relationships,
            image_cache,
        )

        result.update({
            "name": properties.get("name"),
            "id": properties.get("id"),
            "extent": extent,
            "position": position,
            "container": container_name,
        })

        return result

    if shape is not None:

        result = _extract_shape(
            shape
        )

        result.update({
            "extent": extent,
            "position": position,
            "container": container_name,
        })

        return result

    if picture is not None:

        result = _extract_picture(
            picture,
            zip_file,
            relationships,
            image_cache,
        )

        result.update({
            "extent": extent,
            "position": position,
            "container": container_name,
        })

        return result

    return None


def _collect_group_text(node: dict) -> list[dict]:

    elements = []

    for child in node.get(
        "children",
        []
    ):

        if child.get("type") == "shape":

            text = child.get(
                "text",
                ""
            ).strip()

            if text:

                elements.append({
                    "type": "shape_text",
                    "text": text,
                    "name": child.get(
                        "name"
                    ),
                    "id": child.get(
                        "id"
                    ),
                    "extent": child.get(
                        "extent",
                        {}
                    ),
                })

        elif child.get("type") == "picture":

            text = child.get(
                "text",
                ""
            ).strip()

            if text:

                elements.append({
                    "type": "picture_text",
                    "text": text,
                })

        elif child.get("type") == "group":

            elements.extend(
                _collect_group_text(
                    child
                )
            )

    return elements


def _collect_group_images(
    node: dict,
    seen_paths: set[str] | None = None,
) -> list[dict]:

    if seen_paths is None:
        seen_paths = set()

    images = []

    for image in node.get(
        "images",
        []
    ):

        archive_path = image.get(
            "archive_path"
        )

        if not archive_path:
            continue

        if archive_path in seen_paths:
            continue

        seen_paths.add(
            archive_path
        )

        images.append(
            image
        )

    for child in node.get(
        "children",
        []
    ):

        images.extend(
            _collect_group_images(
                child,
                seen_paths,
            )
        )

    return images


def _make_diagram_content(
    drawing: dict,
) -> dict:

    images = _collect_group_images(
        drawing
    )

    return {
        "name": drawing.get(
            "name"
        ),
        "id": drawing.get(
            "id"
        ),
        "extent": drawing.get(
            "extent",
            {}
        ),
        "position": drawing.get(
            "position",
            {}
        ),
        "container": drawing.get(
            "container"
        ),
        "text_elements": _collect_group_text(
            drawing
        ),
        "image_assets": [
            {
                "relationship_id": image.get(
                    "relationship_id"
                ),
                "target": image.get(
                    "target"
                ),
                "archive_path": image.get(
                    "archive_path"
                ),
                "mime_type": image.get(
                    "mime_type"
                ),
                "size_bytes": image.get(
                    "size_bytes"
                ),
                "image_bytes": image.get(
                    "image_bytes"
                ),
            }
            for image in images
        ],
        "structure": drawing,
    }


def _add_drawing_block(
    content_blocks: list[dict],
    drawing: dict,
    order: int,
) -> int:

    drawing_type = drawing.get(
        "type"
    )

    if drawing_type == "shape":

        text = drawing.get(
            "text",
            ""
        ).strip()

        if not text:
            return order

        content_blocks.append(
            create_content_block(
                block_id=f"p1_b{order}",
                block_type="text",
                content=text,
                source="docx",
                order=order,
                page_number=1,
                location={
                    "extent": drawing.get(
                        "extent",
                        {}
                    ),
                    "position": drawing.get(
                        "position",
                        {}
                    ),
                },
                provenance={
                    "extraction_method": "docx_drawingml",
                    "drawing_type": "shape",
                    "drawing_name": drawing.get(
                        "name"
                    ),
                    "drawing_id": drawing.get(
                        "id"
                    ),
                },
            )
        )

        return order + 1

    if drawing_type == "picture":

        for image in drawing.get(
            "images",
            []
        ):

            content_blocks.append(
                create_content_block(
                    block_id=f"p1_b{order}",
                    block_type="image",
                    content={
                        "mime_type": image.get(
                            "mime_type"
                        ),
                        "size_bytes": image.get(
                            "size_bytes"
                        ),
                        "image_bytes": image.get(
                            "image_bytes"
                        ),
                    },
                    source="docx",
                    order=order,
                    page_number=1,
                    location={
                        "extent": drawing.get(
                            "extent",
                            {}
                        ),
                        "position": drawing.get(
                            "position",
                            {}
                        ),
                    },
                    provenance={
                        "extraction_method": "docx_drawingml",
                        "drawing_type": "picture",
                        "drawing_name": drawing.get(
                            "name"
                        ),
                        "drawing_id": drawing.get(
                            "id"
                        ),
                        "archive_path": image.get(
                            "archive_path"
                        ),
                        "relationship_id": image.get(
                            "relationship_id"
                        ),
                    },
                )
            )

            order += 1

        return order

    if drawing_type == "group":

        content = _make_diagram_content(
            drawing
        )

        if not content["text_elements"] and not content["image_assets"]:
            return order

        content_blocks.append(
            create_content_block(
                block_id=f"p1_b{order}",
                block_type="diagram",
                content=content,
                source="docx",
                order=order,
                page_number=1,
                location={
                    "extent": drawing.get(
                        "extent",
                        {}
                    ),
                    "position": drawing.get(
                        "position",
                        {}
                    ),
                },
                provenance={
                    "extraction_method": "docx_drawingml",
                    "drawing_type": "group",
                    "drawing_name": drawing.get(
                        "name"
                    ),
                    "drawing_id": drawing.get(
                        "id"
                    ),
                },
            )
        )

        return order + 1

    return order


def extract_docx(
    file_bytes: bytes,
    file_name: str | None = None,
) -> dict:

    document = Document(
        BytesIO(file_bytes)
    )

    content_blocks = []
    order = 1

    # ---------------------------------------------------------
    # Normal text
    # ---------------------------------------------------------

    for paragraph in document.paragraphs:

        text = paragraph.text.strip()

        if not text:
            continue

        content_blocks.append(
            create_content_block(
                block_id=f"p1_b{order}",
                block_type="text",
                content=text,
                source="docx",
                order=order,
                page_number=1,
                provenance={
                    "extraction_method": "python-docx"
                },
            )
        )

        order += 1

    # ---------------------------------------------------------
    # Tables
    # ---------------------------------------------------------

    for table_index, table in enumerate(
        document.tables,
        start=1,
    ):

        rows = []

        for row in table.rows:

            rows.append([
                cell.text.strip()
                for cell in row.cells
            ])

        if not rows:
            continue

        content_blocks.append(
            create_content_block(
                block_id=f"p1_b{order}",
                block_type="table",
                content={
                    "rows": rows
                },
                source="docx",
                order=order,
                page_number=1,
                provenance={
                    "extraction_method": "python-docx",
                    "table_index": table_index,
                },
            )
        )

        order += 1

    # ---------------------------------------------------------
    # DrawingML
    # ---------------------------------------------------------

    image_cache = {}

    drawing_count = 0
    shape_count = 0
    group_count = 0
    picture_count = 0

    with ZipFile(
        BytesIO(file_bytes),
        "r"
    ) as zip_file:

        document_root = ET.fromstring(
            zip_file.read(
                DOCUMENT_XML
            )
        )

        relationships = _load_relationships(
            zip_file
        )

        # IMPORTANT:
        # Search by local XML tag name rather than
        # depending on namespace prefix resolution.
        drawings = [
            node
            for node in document_root.iter()
            if node.tag.endswith("}drawing")
        ]

        for drawing in drawings:

            extracted = _extract_drawing(
                drawing,
                zip_file,
                relationships,
                image_cache,
            )

            if extracted is None:
                continue

            drawing_count += 1

            drawing_type = extracted.get(
                "type"
            )

            if drawing_type == "shape":
                shape_count += 1

            elif drawing_type == "group":
                group_count += 1

            elif drawing_type == "picture":
                picture_count += 1

            order = _add_drawing_block(
                content_blocks,
                extracted,
                order,
            )

    page = create_page(
        page_number=1,
        content_blocks=content_blocks,
        dimensions={},
        evidence={
            "extraction_method": "python-docx + DrawingML XML",
            "drawing_count": drawing_count,
            "shape_count": shape_count,
            "group_count": group_count,
            "picture_count": picture_count,
            "unique_embedded_images": len(
                image_cache
            ),
        },
    )

    return create_source_document(
        source_type="docx",
        file_name=file_name,
        pages=[page],
        metadata={
            "drawingml_enabled": True,
            "unique_embedded_images": len(
                image_cache
            ),
        },
    )