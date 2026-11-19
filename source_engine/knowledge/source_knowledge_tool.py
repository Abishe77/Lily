from source_engine.retrieval.chunk_retrieval import (
    retrieve_source_chunks,
)
from source_engine.retrieval.discovery_retrieval import (
    retrieve_discovery_units,
)
from source_engine.ingestion.source_ingestion_pipeline import (
    ingest_targeted_source_units,
)
from source_engine.embeddings.chunk_embedding_pipeline import (
    embed_source_chunks,
)


def get_source_cache_state(cur, source_id: int) -> dict:
    """
    Return the current deep-cache state for a source.
    """

    cur.execute(
        """
        SELECT
            COUNT(*) AS total_units,
            COUNT(*) FILTER (
                WHERE status = 'ingested'
            ) AS ingested_units
        FROM source_units
        WHERE source_id = %s;
        """,
        (source_id,),
    )

    total_units, ingested_units = cur.fetchone()

    total_units = int(total_units or 0)
    ingested_units = int(ingested_units or 0)

    return {
        "total_units": total_units,
        "ingested_units": ingested_units,
        "remaining_units": total_units - ingested_units,
        "fully_ingested": (
            total_units > 0
            and total_units == ingested_units
        ),
    }


def _find_uningested_discovery_candidates(
    cur,
    query: str,
    source_id: int,
    top_k: int = 5,
) -> list[dict]:
    """
    Search the cheap discovery cache and return only candidate
    units that have NOT already been deeply ingested.
    """

    discovery_results = retrieve_discovery_units(
        cur=cur,
        query=query,
        source_id=source_id,
        top_k=top_k,
    )

    if not discovery_results:
        return []

    candidate_ids = [
        result["unit_id"]
        for result in discovery_results
    ]

    cur.execute(
        """
        SELECT id
        FROM source_units
        WHERE source_id = %s
          AND id = ANY(%s)
          AND status != 'ingested';
        """,
        (source_id, candidate_ids),
    )

    uningested_ids = {
        row[0]
        for row in cur.fetchall()
    }

    return [
        result
        for result in discovery_results
        if result["unit_id"] in uningested_ids
    ]


def get_source_knowledge(
    cur,
    query: str,
    source_id: int,
    top_k: int = 5,
    allow_targeted_ingestion: bool = True,
    max_new_units: int | None = None,
) -> dict:


    if not query or not query.strip():
        raise ValueError("Query cannot be empty")

    if max_new_units is not None and max_new_units<0:
        raise ValueError("max_new_units cannot be negative")

    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")



    cache_state_before = get_source_cache_state(
        cur=cur,
        source_id=source_id,
    )

    if cache_state_before["total_units"] == 0:
        return {
            "source_id": source_id,
            "query": query,
            "cache_status": "no_discovery_cache",
            "knowledge_available": False,
            "cache_state": cache_state_before,
            "chunks": [],
            "targeted_ingestion": None,
        }


    deep_chunks_before = retrieve_source_chunks(
        cur=cur,
        query=query,
        source_id=source_id,
        top_k=top_k,
    )


    if cache_state_before["fully_ingested"]:
        return {
            "source_id": source_id,
            "query": query,
            "cache_status": "fully_cached",
            "knowledge_available": bool(deep_chunks_before),
            "cache_state": cache_state_before,
            "chunks": deep_chunks_before,
            "targeted_ingestion": None,
        }


    if not allow_targeted_ingestion:
        return {
            "source_id": source_id,
            "query": query,
            "cache_status": "partial_cache",
            "knowledge_available": bool(deep_chunks_before),
            "cache_state": cache_state_before,
            "chunks": deep_chunks_before,
            "targeted_ingestion": None,
        }

    if max_new_units ==0:
        return{
            "source_id" : source_id,
            "query" : query,
            "cache_status" : "partial_cache_budget_exhausted",
            "knowledge_available" : bool(deep_chunks_before),
            "cache_state" : cache_state_before,
            "chunks" : deep_chunks_before,
            "targeted_ingestion" :{
                "candidate_units" : [],
                "units_processed" : 0,
                "chunks_created" : 0,
                "embeddings_written" : 0,
            } ,
        }

    

    discovery_candidates = _find_uningested_discovery_candidates(
        cur=cur,
        query=query,
        source_id=source_id,
        top_k=top_k,
    )

    if not discovery_candidates:
        return {
            "source_id": source_id,
            "query": query,
            "cache_status": "partial_cache_no_new_candidates",
            "knowledge_available": bool(deep_chunks_before),
            "cache_state": cache_state_before,
            "chunks": deep_chunks_before,
            "targeted_ingestion": {
                "candidate_units": [],
                "units_processed": 0,
                "chunks_created": 0,
                "embeddings_written": 0,
            },
        }

    selected_candidates = discovery_candidates

    if max_new_units is not None:
        selected_candidates = discovery_candidates[:max_new_units]

    target_unit_ids = [
        candidate["unit_id"]
        for candidate in selected_candidates
    ]    

    # ---------------------------------------------------------
    # STEP 6: DEEP-INGEST ONLY THE DISCOVERY CANDIDATES
    # ---------------------------------------------------------

    ingestion_result = ingest_targeted_source_units(
        cur=cur,
        source_id=source_id,
        unit_ids=target_unit_ids,
    )

    

    embeddings_written = 0

    if ingestion_result["chunks_created"] > 0:
        embeddings_written = embed_source_chunks(
            cur=cur,
            source_id=source_id,
        )

    

    deep_chunks_after = retrieve_source_chunks(
        cur=cur,
        query=query,
        source_id=source_id,
        top_k=top_k,
    )

    cache_state_after = get_source_cache_state(
        cur=cur,
        source_id=source_id,
    )

    return {
        "source_id": source_id,
        "query": query,
        "cache_status": "targeted_ingestion_completed",
        "knowledge_available": bool(deep_chunks_after),
        "cache_state": cache_state_after,
        "chunks": deep_chunks_after,

        "targeted_ingestion": {
            "candidate_units": [
                {
                    "unit_id": candidate["unit_id"],
                    "unit_index": candidate["unit_index"],
                    "similarity": candidate["similarity"],
                }
                for candidate in selected_candidates
            ],
            "units_processed": ingestion_result["units_processed"],
            "chunks_created": ingestion_result["chunks_created"],
            "embeddings_written": embeddings_written,
        },
    }