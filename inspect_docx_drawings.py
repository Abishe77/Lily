from pathlib import Path
from collections import Counter
from zipfile import ZipFile
import xml.etree.ElementTree as ET


DOCX_PATH = Path("V CODERS.docx")
DOCUMENT_XML = "word/document.xml"
RELATIONSHIPS_XML = "word/_rels/document.xml.rels"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "v": "urn:schemas-microsoft-com:vml",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def get_attr(element, namespace: str, name: str):
    return element.get(f"{{{namespace}}}{name}")


def load_relationships(zip_file: ZipFile) -> dict:
    if RELATIONSHIPS_XML not in zip_file.namelist():
        return {}

    root = ET.fromstring(zip_file.read(RELATIONSHIPS_XML))

    relationships = {}

    for relationship in root.findall("pr:Relationship", NS):
        relationship_id = relationship.get("Id")
        target = relationship.get("Target")
        relationship_type = relationship.get("Type")

        relationships[relationship_id] = {
            "target": target,
            "type": relationship_type,
        }

    return relationships


def extract_text(element) -> str:
    texts = []

    for text_node in element.findall(".//w:t", NS):
        if text_node.text:
            texts.append(text_node.text)

    return "".join(texts).strip()


def extract_extent(element) -> dict | None:
    extent = element.find("wp:extent", NS)

    if extent is None:
        return None

    return {
        "cx": extent.get("cx"),
        "cy": extent.get("cy"),
    }


def extract_anchor_position(element) -> dict:
    result = {}

    position_h = element.find("wp:positionH", NS)
    position_v = element.find("wp:positionV", NS)

    if position_h is not None:
        result["horizontal_relative_from"] = position_h.get("relativeFrom")

        offset = position_h.find("wp:posOffset", NS)
        if offset is not None:
            result["horizontal_offset"] = offset.text

    if position_v is not None:
        result["vertical_relative_from"] = position_v.get("relativeFrom")

        offset = position_v.find("wp:posOffset", NS)
        if offset is not None:
            result["vertical_offset"] = offset.text

    return result


def get_object_name(element) -> str | None:
    doc_pr = element.find("wp:docPr", NS)

    if doc_pr is None:
        return None

    return doc_pr.get("name")


def get_object_id(element) -> str | None:
    doc_pr = element.find("wp:docPr", NS)

    if doc_pr is None:
        return None

    return doc_pr.get("id")


def get_embedded_images(element, relationships: dict) -> list:
    images = []

    for blip in element.findall(".//a:blip", NS):
        relationship_id = get_attr(
            blip,
            NS["r"],
            "embed"
        )

        if not relationship_id:
            continue

        relationship = relationships.get(relationship_id, {})

        images.append({
            "relationship_id": relationship_id,
            "target": relationship.get("target"),
        })

    return images


def classify_drawing(element) -> str:
    if element.find(".//wps:wsp", NS) is not None:
        return "shape"

    if element.find(".//wpg:wgp", NS) is not None:
        return "group"

    if element.find(".//pic:pic", NS) is not None:
        return "picture"

    return "drawing"


def extract_drawing_info(drawing, relationships: dict) -> dict:
    inline = drawing.find("wp:inline", NS)
    anchor = drawing.find("wp:anchor", NS)

    container = inline if inline is not None else anchor

    if container is None:
        return {
            "type": "unknown",
            "name": None,
            "id": None,
            "text": "",
            "extent": None,
            "position": {},
            "images": [],
            "group_children": 0,
        }

    object_type = classify_drawing(container)

    name = get_object_name(container)
    object_id = get_object_id(container)

    text = extract_text(container)

    extent = extract_extent(container)

    position = {}
    if anchor is not None:
        position = extract_anchor_position(anchor)

    images = get_embedded_images(container, relationships)

    group = container.find(".//wpg:wgp", NS)
    group_children = 0

    if group is not None:
        group_children = len(list(group))

    return {
        "type": object_type,
        "container": "inline" if inline is not None else "anchor",
        "name": name,
        "id": object_id,
        "text": text,
        "extent": extent,
        "position": position,
        "images": images,
        "group_children": group_children,
    }


def main():
    if not DOCX_PATH.exists():
        raise FileNotFoundError(
            f"Could not find: {DOCX_PATH.resolve()}"
        )

    with ZipFile(DOCX_PATH, "r") as zip_file:
        document_root = ET.fromstring(
            zip_file.read(DOCUMENT_XML)
        )

        relationships = load_relationships(zip_file)

    drawings = document_root.findall(".//w:drawing", NS)

    print("=" * 80)
    print("DOCX DRAWING DIAGNOSTIC")
    print("=" * 80)
    print(f"File: {DOCX_PATH}")
    print(f"Total w:drawing elements: {len(drawings)}")
    print()

    objects = []

    for index, drawing in enumerate(drawings, start=1):
        info = extract_drawing_info(
            drawing,
            relationships
        )

        info["drawing_index"] = index
        objects.append(info)

    type_counts = Counter(
        obj["type"]
        for obj in objects
    )

    container_counts = Counter(
        obj["container"]
        for obj in objects
    )

    text_objects = [
        obj
        for obj in objects
        if obj["text"]
    ]

    image_objects = [
        obj
        for obj in objects
        if obj["images"]
    ]

    group_objects = [
        obj
        for obj in objects
        if obj["type"] == "group"
    ]

    print("OBJECT TYPE COUNTS")
    print("-" * 80)

    for object_type, count in type_counts.most_common():
        print(f"{object_type:15} {count}")

    print()

    print("CONTAINER COUNTS")
    print("-" * 80)

    for container_type, count in container_counts.most_common():
        print(f"{container_type:15} {count}")

    print()

    print("SUMMARY")
    print("-" * 80)
    print(f"Drawings with text:   {len(text_objects)}")
    print(f"Drawings with images: {len(image_objects)}")
    print(f"Groups:               {len(group_objects)}")
    print()

    print("=" * 80)
    print("TEXT-BEARING OBJECTS")
    print("=" * 80)

    shown = 0

    for obj in text_objects:
        shown += 1

        text = obj["text"].replace("\n", " ")

        if len(text) > 180:
            text = text[:180] + "..."

        print()
        print(f"Drawing #{obj['drawing_index']}")
        print(f"  Type:      {obj['type']}")
        print(f"  Container: {obj['container']}")
        print(f"  Name:      {obj['name']}")
        print(f"  ID:        {obj['id']}")
        print(f"  Extent:    {obj['extent']}")
        print(f"  Position:  {obj['position']}")
        print(f"  Text:      {text}")

        if obj["images"]:
            print(f"  Images:    {obj['images']}")

        if obj["group_children"]:
            print(f"  Children:  {obj['group_children']}")

        if shown >= 50:
            print()
            print("... showing first 50 text-bearing objects ...")
            break

    print()

    print("=" * 80)
    print("IMAGE-BEARING OBJECTS")
    print("=" * 80)

    shown = 0

    for obj in image_objects:
        shown += 1

        print()
        print(f"Drawing #{obj['drawing_index']}")
        print(f"  Type:      {obj['type']}")
        print(f"  Container: {obj['container']}")
        print(f"  Name:      {obj['name']}")
        print(f"  ID:        {obj['id']}")
        print(f"  Extent:    {obj['extent']}")
        print(f"  Position:  {obj['position']}")
        print(f"  Images:    {obj['images']}")

        if obj["text"]:
            text = obj["text"].replace("\n", " ")
            if len(text) > 120:
                text = text[:120] + "..."
            print(f"  Text:      {text}")

        if shown >= 30:
            print()
            print("... showing first 30 image-bearing objects ...")
            break

    print()

    print("=" * 80)
    print("RELATIONSHIP / MEDIA CHECK")
    print("=" * 80)

    media_relationships = []

    for relationship_id, relationship in relationships.items():
        target = relationship.get("target", "")

        if "media/" in target:
            media_relationships.append(
                (
                    relationship_id,
                    target
                )
            )

    print(f"Media relationships: {len(media_relationships)}")

    for relationship_id, target in media_relationships[:50]:
        print(f"  {relationship_id} -> {target}")

    if len(media_relationships) > 50:
        print("  ...")

    print()
    print("=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()