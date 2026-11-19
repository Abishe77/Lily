from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


DOCX_PATH = Path("V CODERS.docx")
DOCUMENT_XML = "word/document.xml"


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def get_attr(element, namespace: str, name: str):
    return element.get(f"{{{namespace}}}{name}")


def extract_text(element) -> str:
    parts = []

    for node in element.findall(".//w:t", NS):
        if node.text:
            parts.append(node.text)

    return "".join(parts).strip()


def get_name(element):
    doc_pr = element.find("wp:docPr", NS)

    if doc_pr is not None:
        return doc_pr.get("name")

    return None


def get_id(element):
    doc_pr = element.find("wp:docPr", NS)

    if doc_pr is not None:
        return doc_pr.get("id")

    return None


def get_extent(element):
    extent = element.find("wp:extent", NS)

    if extent is None:
        return None

    return {
        "cx": extent.get("cx"),
        "cy": extent.get("cy"),
    }


def get_position(element):
    position = {}

    position_h = element.find("wp:positionH", NS)
    position_v = element.find("wp:positionV", NS)

    if position_h is not None:
        position["horizontal_relative_from"] = position_h.get(
            "relativeFrom"
        )

        offset = position_h.find("wp:posOffset", NS)

        if offset is not None:
            position["horizontal_offset"] = offset.text

    if position_v is not None:
        position["vertical_relative_from"] = position_v.get(
            "relativeFrom"
        )

        offset = position_v.find("wp:posOffset", NS)

        if offset is not None:
            position["vertical_offset"] = offset.text

    return position


def classify_container(element):
    if element.find("wpg:wgp", NS) is not None:
        return "group"

    if element.find("wps:wsp", NS) is not None:
        return "shape"

    if element.find("pic:pic", NS) is not None:
        return "picture"

    return "unknown"


def find_direct_group_children(group):
    """
    Return direct semantic children of a DrawingML group.

    We intentionally avoid .// here because we want to see
    the actual hierarchy rather than flattening nested objects.
    """

    children = []

    for child in list(group):

        tag = child.tag

        if tag == f"{{{NS['wpg']}}}wgp":
            children.append({
                "element": child,
                "type": "group",
            })

        elif tag == f"{{{NS['wps']}}}wsp":
            children.append({
                "element": child,
                "type": "shape",
            })

        elif tag == f"{{{NS['pic']}}}pic":
            children.append({
                "element": child,
                "type": "picture",
            })

        elif tag == f"{{{NS['a']}}}graphic":
            # Graphic containers themselves are not semantic objects.
            continue

    return children


def extract_shape_details(element, object_type):
    text = extract_text(element)

    name = None
    object_id = None
    extent = None

    if object_type in {"shape", "picture"}:
        name = get_name(element)
        object_id = get_id(element)

    return {
        "type": object_type,
        "name": name,
        "id": object_id,
        "text": text,
    }


def print_tree(group, indent="", max_depth=4, depth=0):
    if depth > max_depth:
        print(indent + "... maximum depth reached ...")
        return

    children = find_direct_group_children(group)

    if not children:
        print(indent + "(no direct semantic children)")
        return

    for index, child_info in enumerate(children, start=1):

        element = child_info["element"]
        child_type = child_info["type"]

        text = extract_text(element)

        name = get_name(element)

        extent = get_extent(element)

        print(
            f"{indent}{index}. "
            f"{child_type}"
        )

        if name:
            print(
                f"{indent}   name: {name}"
            )

        object_id = get_id(element)

        if object_id:
            print(
                f"{indent}   id: {object_id}"
            )

        if extent:
            print(
                f"{indent}   extent: {extent}"
            )

        if text:
            text = " ".join(text.split())

            if len(text) > 180:
                text = text[:180] + "..."

            print(
                f"{indent}   text: {text}"
            )

        nested_group = element.find(
            ".//wpg:wgp",
            NS
        )

        if nested_group is not None and child_type == "group":
            print(
                f"{indent}   children:"
            )

            print_tree(
                nested_group,
                indent + "      ",
                max_depth=max_depth,
                depth=depth + 1
            )


def main():

    if not DOCX_PATH.exists():
        raise FileNotFoundError(
            f"Could not find: {DOCX_PATH.resolve()}"
        )

    with ZipFile(DOCX_PATH, "r") as zip_file:
        root = ET.fromstring(
            zip_file.read(DOCUMENT_XML)
        )

    drawings = root.findall(".//w:drawing", NS)

    print("=" * 90)
    print("DOCX GROUP STRUCTURE DIAGNOSTIC")
    print("=" * 90)
    print(f"File: {DOCX_PATH}")
    print(f"Total drawings: {len(drawings)}")
    print()

    group_count = 0

    for drawing_index, drawing in enumerate(
        drawings,
        start=1
    ):

        anchor = drawing.find("wp:anchor", NS)
        inline = drawing.find("wp:inline", NS)

        container = anchor if anchor is not None else inline

        if container is None:
            continue

        group = container.find(
            ".//wpg:wgp",
            NS
        )

        if group is None:
            continue

        group_count += 1

        name = get_name(container)
        object_id = get_id(container)
        extent = get_extent(container)
        position = get_position(container)

        group_text = extract_text(container)

        print()
        print("=" * 90)
        print(
            f"GROUP #{group_count} "
            f"(Drawing #{drawing_index})"
        )
        print("=" * 90)

        print(f"Type:      group")
        print(f"Name:      {name}")
        print(f"ID:        {object_id}")
        print(f"Extent:    {extent}")
        print(f"Position:  {position}")

        if group_text:
            text = " ".join(group_text.split())

            if len(text) > 300:
                text = text[:300] + "..."

            print(f"Group text: {text}")

        print()
        print("CHILDREN")
        print("-" * 90)

        print_tree(
            group,
            indent="",
            max_depth=5
        )

        # The first 9 groups are currently known from the
        # diagnostic, so print all of them.
        # If the document becomes much larger later,
        # this can be changed to a limit.

    print()
    print("=" * 90)
    print("DONE")
    print("=" * 90)
    print(f"Groups inspected: {group_count}")


if __name__ == "__main__":
    main()