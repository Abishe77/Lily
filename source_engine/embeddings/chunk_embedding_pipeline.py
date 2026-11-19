from source_engine.embeddings.qwen_embedding import embed_text


EMBEDDING_MODEL = "Qwen3-Embedding-0.6B"


def embed_source_chunks(cur, source_id: int) -> int:
    """
    Generate and store embeddings for all source chunks
    belonging to a source.
    """

    cur.execute(
        """
        SELECT
            sc.id,
            sc.retrieval_text
        FROM source_chunks sc
        JOIN source_units su
            ON su.id = sc.source_unit_id
        WHERE su.source_id = %s
          AND sc.retrieval_text IS NOT NULL
          AND TRIM(sc.retrieval_text) <> ''
        ORDER BY sc.id;
        """,
        (source_id,),
    )

    chunks = cur.fetchall()

    embedded_count = 0

    for chunk_id, retrieval_text in chunks:

        embedding = embed_text(retrieval_text)

        vector_text = "[" + ",".join(
            str(value) for value in embedding
        ) + "]"

        cur.execute(
            """
            INSERT INTO source_chunk_embeddings (
                source_chunk_id,
                embedding,
                embedding_model
            )
            VALUES (%s, %s::vector, %s)
            ON CONFLICT (source_chunk_id)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model;
            """,
            (
                chunk_id,
                vector_text,
                EMBEDDING_MODEL,
            ),
        )

        embedded_count += 1

    return embedded_count