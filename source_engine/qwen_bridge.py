import tempfile
from pathlib import Path
from io import BytesIO

from PIL import Image

from source_engine.qwen_vision import extract_visual_content


def analyze_page_with_qwen(
    image_bytes: bytes
) -> dict:

    temporary_path = None

    try:

        image = Image.open(
            BytesIO(image_bytes)
        )

        if image.mode not in {
            "RGB",
            "RGBA"
        }:

            image = image.convert(
                "RGB"
            )

        elif image.mode == "RGBA":

            background = Image.new(
                "RGB",
                image.size,
                "white"
            )

            background.paste(
                image,
                mask=image.getchannel(
                    "A"
                )
            )

            image = background

        with tempfile.NamedTemporaryFile(
            suffix=".png",
            delete=False
        ) as temporary_file:

            temporary_path = Path(
                temporary_file.name
            )

        image.save(
            temporary_path,
            format="PNG"
        )

        result = extract_visual_content(
            str(temporary_path)
        )

        return result

    finally:

        if (
            temporary_path
            and temporary_path.exists()
        ):

            temporary_path.unlink()

