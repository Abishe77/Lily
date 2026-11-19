
from uuid import uuid4
import hashlib
import uuid
from pathlib import Path


# ---------------------------------------------------------
# Storage root
#
# During local development, original source files live here.
# Later this implementation can be replaced by S3/object
# storage without changing the rest of Lily.
# ---------------------------------------------------------

STORAGE_ROOT = Path("data") / "sources"


def calculate_file_hash(file_bytes: bytes) -> str:
    """
    Return SHA-256 identity for an uploaded source.
    """

    return hashlib.sha256(file_bytes).hexdigest()


def build_storage_key(
    user_id: int,
    file_hash: str,
    filename: str,
) -> str:
    suffix = Path(filename).suffix.lower()

    storage_path = (
        Path(str(user_id))
        / f"{file_hash}_{uuid.uuid4().hex}{suffix}"
    )

    return storage_path.as_posix()

def save_source_file(
    file_bytes: bytes,
    storage_key: str
) -> None:
    """
    Persist the original source bytes.

    storage_key is relative to STORAGE_ROOT.
    """

    destination = STORAGE_ROOT / storage_key

    destination.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    destination.write_bytes(file_bytes)


def delete_source_file(
    storage_key: str
) -> None:
    """
    Remove a stored source.

    Primarily useful when DB registration fails after the
    physical file has already been written.
    """

    path = STORAGE_ROOT / storage_key

    if path.exists():
        path.unlink()


def get_source_path(
    storage_key: str
) -> Path:
    """
    Resolve a storage key into the local physical path.
    """

    return STORAGE_ROOT / storage_key


def read_source_file(
    storage_key: str
) -> bytes:
    """
    Load the original source bytes.

    Targeted ingestion will eventually use this to reopen a
    PDF/PPTX/etc. weeks after initial upload.
    """

    path = get_source_path(storage_key)

    if not path.exists():
        raise FileNotFoundError(
            f"Stored source not found: {storage_key}"
        )

    return path.read_bytes()