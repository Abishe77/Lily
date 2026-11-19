from source_engine.embeddings.discovery_embeddings import embed_discovery_text


def retrieve_source_chunks(
    cur,
    query: str,
    source_id: int,
    top_k: int = 5,
) -> list[dict]:
    if not query or not query.strip():
        raise ValueError("Query cannot be empty.")

    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")

    query_embedding = embed_discovery_text(query)

    vector_text = "[" + ",".join(
        str(value) for value in query_embedding
    ) + "]"

    cur.execute(
        """
        SELECT
            sc.id,
            sc.source_unit_id,
            sc.chunk_index,
            sc.chunk_type,
            sc.retrieval_text,
            1 - (sce.embedding <=> %s::vector) AS similarity
        FROM source_chunks sc
        JOIN source_units su
            ON su.id = sc.source_unit_id
        JOIN source_chunk_embeddings sce
            ON sce.source_chunk_id = sc.id
        WHERE su.source_id = %s
        ORDER BY sce.embedding <=> %s::vector
        LIMIT %s;
        """,
        (
            vector_text,
            source_id,
            vector_text,
            top_k,
        ),
    )

    rows = cur.fetchall()

    results = []

    for row in rows:
        (
            chunk_id,
            source_unit_id,
            chunk_index,
            chunk_type,
            retrieval_text,
            similarity,
        ) = row

        results.append(
            {
                "chunk_id": chunk_id,
                "source_unit_id": source_unit_id,
                "chunk_index": chunk_index,
                "chunk_type": chunk_type,
                "retrieval_text": retrieval_text,
                "similarity": float(similarity),
            }
        )

    return results