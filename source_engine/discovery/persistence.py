from datetime import datetime, timezone
from psycopg2.extras import Json

from source_engine.discovery.models import (
    DiscoveredUnit,
    DiscoveryResult,
)


def persist_discovery(
    cur,
    source_id: int,
    result: DiscoveryResult,
) -> dict:
    """
    Persist discovery results for one source.

    Existing discovery units for the source are replaced so that
    re-running discovery produces a clean, deterministic result.
    """

    cur.execute(
        """
        DELETE FROM source_units
        WHERE source_id = %s;
        """,
        (source_id,),
    )

    discovered_count = 0
    unresolved_count = 0

    for unit in result.units:

        status = (
            "discovered"
            if unit.discovery_method not in {
                "vision_failed",
                "vision_weak",
            }
            else "unresolved"
        )

        if status == "discovered":
            discovered_count += 1
        else:
            unresolved_count += 1

        cur.execute(
            """
            INSERT INTO source_units (
                source_id,
                unit_index,
                unit_type,
                discovery_text,
                discovery_metadata,
                discovery_method,
                discovery_confidence,
                discovery_observed,
                status,
                discovered_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            );
            """,
            (
                source_id,
                unit.unit_index,
                unit.unit_type,
                unit.discovery_text,
                Json(unit.discovery_metadata),
                unit.discovery_method,
                unit.discovery_confidence,
                unit.discovery_observed,
                status,
                datetime.now(timezone.utc),
            ),
        )

    total_units = len(result.units)

    if unresolved_count == 0 and total_units > 0:
        discovery_status = "discovered"
    elif discovered_count > 0:
        discovery_status = "partial"
    else:
        discovery_status = "failed"

    cur.execute(
        """
        UPDATE sources
        SET
            discovery_status = %s,
            discovered_at = %s
        WHERE id = %s;
        """,
        (
            discovery_status,
            datetime.now(timezone.utc),
            source_id,
        ),
    )

    return {
        "discovery_status": discovery_status,
        "total_units": total_units,
        "discovered_units": discovered_count,
        "unresolved_units": unresolved_count,
        "source_type": result.source_type,
        "discovery_metadata": result.metadata,
    }