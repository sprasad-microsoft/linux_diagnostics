import logging
from abc import ABC, abstractmethod
import numpy as np

logger = logging.getLogger(__name__)


class AnomalyHandler(ABC):
    """Base class for anomaly handlers."""

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def detect(self, events_batch: np.ndarray) -> bool:
        """Return True if anomaly detected."""
