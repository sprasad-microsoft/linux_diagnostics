from enum import Enum

class AnomalyType(Enum):
    """Enumeration for different types of anomalies that can be detected."""
    LATENCY = "latency"
    ERROR = "error"
    # Add more types as needed
