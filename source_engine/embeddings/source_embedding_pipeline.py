from source_engine.embeddings.qwen_embedding import embed_text


def build_source_representation(
    cur,
    source_id: int,
) -> str:
    """
    Build the semantic representation used to identify what an
    entire source is about.

    This is for source-library retrieval, not deep knowledge retrieval.
    """

    cur.execute(
        """
        SELECT
            s.filename,
            s.source_type,
            su.unit_index,
            su.discovery_text
        FROM sources s
        LEFT JOIN source_units su
            ON su.source_id = s.id
        WHERE s.id = %s
        ORDER BY su.unit_index;
        """,
        (source_id,),
    )

    rows = cur.fetchall()

    if not rows:
        raise ValueError(
            f"Source {source_id} does not exist."
        )

    filename = rows[0][0]
    source_type = rows[0][1]

    discovery_parts = []

    for _, _, unit_index, discovery_text in rows:
        if not discovery_text:
            continue

        discovery_text = discovery_text.strip()

        if not discovery_text:
            continue

        discovery_parts.append(
            f"Unit {unit_index}:\n{discovery_text}"
        )

    if not discovery_parts:
        raise ValueError(
            f"Source {source_id} has no discovery text."
        )

    return (
        f"Filename: {filename}\n"
        f"Source type: {source_type}\n\n"
        + "\n\n".join(discovery_parts)
    )


def embed_source(
    cur,
    source_id: int,
) -> int:
    """
    Build and persist one semantic embedding representing
    the entire source.

    Returns 1 when the embedding is written.
    """

    representation = build_source_representation(
        cur=cur,
        source_id=source_id,
    )

    embedding = embed_text(representation)

    vector_text = "[" + ",".join(
        str(value) for value in embedding
    ) + "]"

    cur.execute(
        """
        INSERT INTO source_embeddings (
            source_id,
            embedding,
            embedding_model
        )
        VALUES (
            %s,
            %s::vector,
            %s
        )
        ON CONFLICT (source_id)
        DO UPDATE SET
            embedding = EXCLUDED.embedding,
            embedding_model = EXCLUDED.embedding_model,
            updated_at = NOW();
        """,
        (
            source_id,
            vector_text,
            "Qwen3-Embedding-0.6B",
        ),
    )

    return 1