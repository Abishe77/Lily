from source_engine.embeddings.discovery_embeddings import (
    embed_discovery_text,
)


def retrieve_discovery_units(
    cur,
    query: str,
    source_id: int,
    top_k: int = 5,
    min_similarity: float = 0.0,
) -> list[dict]:
    """
    Retrieve the most semantically relevant discovered source units.

    The query is embedded using the same Qwen3 embedding model used
    for source-unit embeddings. PostgreSQL then performs cosine
    similarity search over the stored vectors.

    min_similarity is a semantic relevance floor. Results whose
    cosine similarity is below this value are excluded.

    It defaults to 0.0 so retrieval behavior remains unchanged while
    similarity scores are being evaluated.
    """

    if not query or not query.strip():
        raise ValueError("Query cannot be empty.")

    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    if not 0.0 <= min_similarity <= 1.0:
        raise ValueError(
            "min_similarity must be between 0.0 and 1.0."
        )

    cleaned_query = query.strip()

    query_embedding = embed_discovery_text(cleaned_query)

    vector_text = "[" + ",".join(
        str(value) for value in query_embedding
    ) + "]"

    cur.execute(
        """
        SELECT
            su.id,
            su.unit_index,
            su.unit_type,
            su.discovery_text,
            su.discovery_method,
            su.discovery_confidence,
            1 - (sue.embedding <=> %s::vector) AS similarity
        FROM source_units su
        JOIN source_unit_embeddings sue
            ON sue.source_unit_id = su.id
        WHERE su.source_id = %s
          AND 1 - (sue.embedding <=> %s::vector) >= %s
        ORDER BY sue.embedding <=> %s::vector
        LIMIT %s;
        """,
        (
            vector_text,
            source_id,
            vector_text,
            min_similarity,
            vector_text,
            top_k,
        ),
    )

    rows = cur.fetchall()

    results = []

    for row in rows:
        (
            unit_id,
            unit_index,
            unit_type,
            discovery_text,
            discovery_method,
            discovery_confidence,
            similarity,
        ) = row

        results.append(
            {
                "unit_id": unit_id,
                "unit_index": unit_index,
                "unit_type": unit_type,
                "discovery_text": discovery_text,
                "discovery_method": discovery_method,
                "discovery_confidence": discovery_confidence,
                "similarity": float(similarity),
            }
        )

    print(
        f"[DISCOVERY RETRIEVAL] "
        f"source_id={source_id} "
        f"query={cleaned_query!r}"
    )

    for result in results:
        discovery_text = result.get("discovery_text") or ""
        preview = " ".join(discovery_text.split())[:180]

        print(
            f"[DISCOVERY MATCH] "
            f"unit_id={result['unit_id']} "
            f"unit_index={result['unit_index']} "
            f"similarity={result['similarity']:.4f} "
            f"confidence={result['discovery_confidence']} "
            f"text={preview!r}"
        )

    return results