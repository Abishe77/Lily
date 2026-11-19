from source_engine.embeddings.discovery_embeddings import embed_discovery_text


def embed_source_units(cur, source_id: int) -> int:
    """
    Generate and persist embeddings for all discovered units
    belonging to a source.

    Returns the number of embeddings written.
    """

    cur.execute(
        """
        SELECT
            id,
            discovery_text
        FROM source_units
        WHERE source_id = %s
          AND discovery_text IS NOT NULL
          AND TRIM(discovery_text) <> ''
        ORDER BY unit_index;
        """,
        (source_id,),
    )

    units = cur.fetchall()

    if not units:
        return 0

    embedded_count = 0

    for unit_id, discovery_text in units:
        embedding = embed_discovery_text(discovery_text)

        vector_text = "[" + ",".join(
            str(value) for value in embedding
        ) + "]"

        cur.execute(
            """
            INSERT INTO source_unit_embeddings (
                source_unit_id,
                embedding,
                embedding_model
            )
            VALUES (
                %s,
                %s::vector,
                %s
            )
            ON CONFLICT (source_unit_id)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model;
            """,
            (
                unit_id,
                vector_text,
                "Qwen3-Embedding-0.6B",
            ),
        )

        embedded_count += 1

    return embedded_count