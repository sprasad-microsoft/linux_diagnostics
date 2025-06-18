from dataclasses import dataclass
from models import AnomalyConfig


@dataclass(slots=True, frozen=True)
class GuardianConfig:
    anomalies: dict[str, AnomalyConfig]
