from source_engine.embeddings.qwen_embedding import embed_text


def embed_discovery_text(discovery_text: str) -> list[float]:
    """
    Generate an embedding for one source-unit discovery description.
    """
    if not discovery_text or not discovery_text.strip():
        raise ValueError("Cannot embed empty discovery text.")

    return embed_text(discovery_text)