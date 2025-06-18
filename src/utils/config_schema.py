"""Top level configuration for the AOD."""

from dataclasses import dataclass, field
from typing import Optional

@dataclass(slots=True, frozen=True)
class AnomalyConfig:
    """AnomalyConfig is a dataclass that defines the configuration for an anomaly detection tool."""
    type: str
    tool: str
    acceptable_count: int
    default_threshold_ms: Optional[int] = None
    track: dict[int, Optional[int]] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)

@dataclass(slots=True, frozen=True)
class GuardianConfig:
    """GuardianConfig will tell which anomalies to detect and how to handle them."""
    anomalies: dict[str, AnomalyConfig]

@dataclass(slots=True, frozen=True)
class WatcherConfig:
    """WatcherConfig will tell which actions to be taken"""
    actions: list[str]

@dataclass(slots=True, frozen=True)
class Config:
    """Top level configuration for the AOD."""
    watch_interval_sec: int
    aod_output_dir: str
    watcher: WatcherConfig
    guardian: GuardianConfig
    cleanup: dict  # could make a dataclass if desired
    audit: dict  # could make a dataclass if desired
