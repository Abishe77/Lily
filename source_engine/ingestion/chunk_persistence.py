from psycopg2.extras import Json


def store_source_chunks(
    cur,
    source_unit_id: int,
    chunks: list[dict],
) -> int:
    """
    Replace the existing chunks for one source unit
    with the newly generated chunks.
    """

    cur.execute(
        """
        DELETE FROM source_chunks
        WHERE source_unit_id = %s;
        """,
        (source_unit_id,),
    )

    stored_count = 0

    for chunk in chunks:
        cur.execute(
            """
            INSERT INTO source_chunks (
                source_unit_id,
                chunk_index,
                chunk_type,
                canonical_content,
                retrieval_text,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                source_unit_id,
                chunk["chunk_index"],
                chunk["chunk_type"],
                Json({
                    "blocks": [
                        {
                            "type": chunk["chunk_type"],
                            "content": chunk["text"],
                        }
                    ]
                }),
                chunk["text"],
                Json(chunk["metadata"]),
            ),
        )

        cur.fetchone()
        stored_count += 1

    return stored_count