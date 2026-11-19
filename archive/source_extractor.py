import io
import tempfile
import os

import fitz
from pypdf import PdfReader

from qwen_vision import extract_visual_content


def extract_source(file_path):
    """
    Temporary image extraction test.

    Sends an image directly to Qwen and returns
    the extracted visual information.
    """

    result = {
        "text": "",
        "visual_content": []
    }

    visual_data = extract_visual_content(file_path)

    result["visual_content"].append(visual_data)

    return result


def extract_pdf_source(pdf_bytes: bytes):
    """
    Extract text and visual information from a PDF.

    Text extraction:
        pypdf

    Visual extraction:
        Qwen2.5-VL
    """

    # --------------------------------------------------
    # Normal PDF text extraction
    # --------------------------------------------------

    reader = PdfReader(io.BytesIO(pdf_bytes))

    page_texts = []
    locations = []

    for page_number, page in enumerate(reader.pages, start=1):

        text = page.extract_text() or ""
        text = text.strip()

        if text:
            page_texts.append(text)

            locations.append({
                "type": "page",
                "value": page_number,
                "text": text
            })

    combined_text = "\n\n".join(page_texts).strip()

    # --------------------------------------------------
    # Visual extraction with Qwen
    # --------------------------------------------------

    document = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    visual_pages = []

    for page_number, page in enumerate(document, start=1):

        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(1.5, 1.5)
        )

        image_bytes = pixmap.tobytes("jpeg")

        temp_file = tempfile.NamedTemporaryFile(
            suffix = ".jpg",
            delete= False
        )

        try:
            temp_file.write(image_bytes)
            temp_file.close()

            visual_data = extract_visual_content(temp_file.name)

        finally:
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)    

        visual_pages.append({
            "page": page_number,
            "visual_content": visual_data
        })

    document.close()

    # --------------------------------------------------
    # Return unified extraction result
    # --------------------------------------------------

    return {
        "text": combined_text,
        "pages": len(reader.pages),
        "extraction_method": "pypdf_plus_qwen",
        "locations": locations,
        "visual_content": visual_pages
    }


# ------------------------------------------------------
# Standalone testing
# ------------------------------------------------------

if __name__ == "__main__":

    PDF_PATH = r"D:\Lily med\test.pdf"

    with open(PDF_PATH, "rb") as f:
        pdf_bytes = f.read()

    result = extract_pdf_source(pdf_bytes)

    print("Pages:", result["pages"])
    print("Extraction method:", result["extraction_method"])
    print("Text length:", len(result["text"]))
    print("Visual pages:", len(result["visual_content"]))