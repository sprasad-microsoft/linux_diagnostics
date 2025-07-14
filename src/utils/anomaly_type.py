from enum import Enum


class AnomalyType(Enum):
    """Enumeration for different types of anomalies that can be detected."""

    LATENCY = "latency"
    ERROR = "error"
    # Add more types as needed


ANOMALY_TYPE_TO_TOOL_ID = {
    AnomalyType.LATENCY: 0,
    AnomalyType.ERROR: -1,  # fill correct value here
    # Add more as needed
}
