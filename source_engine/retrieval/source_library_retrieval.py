from source_engine.embeddings.qwen_embedding import embed_text


def retrieve_relevant_sources(
    cur,
    user_id: int,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Retrieve the user's most semantically relevant sources.

    Sources are ranked using their strongest matching discovery unit
    rather than the whole-source embedding alone.
    """

    if not query or not query.strip():
        raise ValueError("Query cannot be empty.")

    if top_k < 1:
        raise ValueError("top_k must be at least 1.")

    query_embedding = embed_text(query.strip())

    vector_text = "[" + ",".join(
        str(value) for value in query_embedding
    ) + "]"

    cur.execute(
        """
        SELECT
            s.id,
            s.filename,
            s.source_type,
            MAX(
                1 - (sue.embedding <=> %s::vector)
            ) AS similarity
        FROM sources s
        JOIN source_units su
            ON su.source_id = s.id
        JOIN source_unit_embeddings sue
            ON sue.source_unit_id = su.id
        WHERE s.user_id = %s
          AND s.discovery_status = 'discovered'
        GROUP BY
            s.id,
            s.filename,
            s.source_type
        ORDER BY similarity DESC
        LIMIT %s;
        """,
        (
            vector_text,
            user_id,
            top_k,
        ),
    )

    rows = cur.fetchall()

    print("[SOURCE RETRIEVAL]")
    for row in rows:
        print(
            f"source_id={row[0]} "
            f"filename={row[1]} "
            f"similarity={float(row[3]):.4f}"
        )

    return [
        {
            "source_id": row[0],
            "filename": row[1],
            "source_type": row[2],
            "similarity": float(row[3]),
        }
        for row in rows
    ]