"""Top level configuration for the AOD."""

from dataclasses import dataclass
from models.watcher_config import WatcherConfig
from models.guardian_config import GuardianConfig

@dataclass(slots=True, frozen=True)
class Config:
    """Top level configuration for the AOD."""
    watch_interval_sec: int
    aod_output_dir: str
    watcher: WatcherConfig
    guardian: GuardianConfig
    cleanup: dict  # could make a dataclass if desired
    audit: dict  # could make a dataclass if desired