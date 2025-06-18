"""
AnomalyConfig is a dataclass that defines the configuration for an anomaly detection tool.
"""

from dataclasses import dataclass, field
from typing import Optional

@dataclass(slots=True, frozen=True)
class AnomalyConfig:
    """AnomalyConfig is a dataclass that defines the configuration for an anomaly detection tool."""
    type: str
    tool: str
    acceptable_percentage: int
    default_threshold_ms: Optional[int] = None
    track: dict[str, Optional[int]] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
