from functools import lru_cache

import torch
from sentence_transformers import SentenceTransformer


MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_DIMENSION = 1024


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """
    Load the Qwen embedding model once and reuse it.
    Explicitly use float32 for CPU inference.
    """
    return SentenceTransformer(
        MODEL_NAME,
        device="cpu",
        model_kwargs={"dtype": torch.float32},
    )


def embed_text(text: str) -> list[float]:
    """
    Convert one text string into a normalized embedding vector.
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text.")

    model = get_embedding_model()

    embedding = model.encode(
        text,
        normalize_embeddings=True,
    )

    vector = embedding.tolist()

    if len(vector) != EMBEDDING_DIMENSION:
        raise ValueError(
            f"Unexpected embedding dimension: "
            f"{len(vector)}. "
            f"Expected {EMBEDDING_DIMENSION}."
        )

    return vector