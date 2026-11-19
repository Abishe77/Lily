from source_engine.retrieval.source_library_retrieval import (
    retrieve_relevant_sources,
)
from source_engine.knowledge.source_knowledge_tool import (
    get_source_knowledge,
)


def get_user_source_knowledge(
    cur,
    user_id: int,
    query: str,
    source_top_k: int = 3,
    chunk_top_k: int = 5,
    allow_targeted_ingestion: bool = True,
    max_new_units : int = 3,
) -> dict:
    """
    Search across a user's source library and retrieve grounded
    knowledge from the most relevant sources.

    The caller does not need to know source IDs.
    """

    if not query or not query.strip():
        raise ValueError("Query cannot be empty.")

    if max_new_units < 0:
        raise ValueError("max_new_units cannot be negative")

    if source_top_k < 1:
        raise ValueError("source_top_k must be at least 1.")

    if chunk_top_k < 1:
        raise ValueError("chunk_top_k must be at least 1.")

    

    source_candidates = retrieve_relevant_sources(
        cur=cur,
        user_id=user_id,
        query=query,
        top_k=source_top_k,
    )

    if not source_candidates:
        return {
            "query": query,
            "knowledge_available": False,
            "sources": [],
            "chunks": [],
        }

    

    source_results = []
    combined_chunks = []


    remaining_new_units = max_new_units
    print(
        f"[SOURCE BUDGET] start={remaining_new_units}"
    )

    for candidate in source_candidates:
        source_id = candidate["source_id"]

        knowledge = get_source_knowledge(
            cur=cur,
            query=query,
            source_id=source_id,
            top_k=chunk_top_k,
            allow_targeted_ingestion=allow_targeted_ingestion,
            max_new_units =  remaining_new_units,
        )

        targeted_ingestion = knowledge.get("targeted_ingestion")

        if targeted_ingestion :
            units_processed = int(
                targeted_ingestion.get("units_processed" , 0)
            )

            remaining_new_units = max(0, remaining_new_units -units_processed,
            )
            print(
    f"[SOURCE BUDGET] source_id={source_id} "
    f"units_processed={units_processed if targeted_ingestion else 0} "
    f"remaining={remaining_new_units}"
)

        chunks = knowledge.get("chunks", [])

        source_result = {
            "source_id": source_id,
            "filename": candidate["filename"],
            "source_type": candidate["source_type"],
            "source_similarity": candidate["similarity"],
            "cache_status": knowledge.get("cache_status"),
            "knowledge_available": bool(chunks),
            "chunks": chunks,
        }

        source_results.append(source_result)

        # Attach source provenance to every returned chunk.
        for chunk in chunks:
            combined_chunks.append(
                {
                    **chunk,
                    "source_id": source_id,
                    "source_filename": candidate["filename"],
                    "source_similarity": candidate["similarity"],
                }
            )

    print(
    f"[SOURCE BUDGET] consumed="
    f"{max_new_units - remaining_new_units} "
    f"remaining={remaining_new_units}"
)

    combined_chunks.sort(
        key=lambda chunk: chunk.get("similarity", 0.0),
        reverse=True,
    )

    return {
        "query": query,
        "knowledge_available": bool(combined_chunks),
        "sources": source_results,
        "chunks": combined_chunks,
    }