from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class WatcherConfig:
    actions: list[str]
