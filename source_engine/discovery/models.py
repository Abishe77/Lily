from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiscoveredUnit:
    """
    Cheap discovery representation of one source unit.

    For a PDF, one unit = one page.

    This is NOT canonical/deep knowledge.
    It only contains enough information to help Lily decide
    where deeper ingestion may be necessary.
    """

    unit_index: int
    unit_type: str

    discovery_text: str | None = None

    discovery_metadata: dict[str, Any] = field(
        default_factory=dict
    )

    discovery_method: str | None = None
    discovery_confidence: float | None = None

    # True only when Lily actually inspected this unit.
    discovery_observed: bool = True


@dataclass
class DiscoveryResult:
    """
    Result of cheap discovery for an entire source.
    """

    source_type: str

    units: list[DiscoveredUnit]

    metadata: dict[str, Any] = field(
        default_factory=dict
    )