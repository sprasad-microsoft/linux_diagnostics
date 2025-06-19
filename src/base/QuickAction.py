"""Abstract base class for quick actions in the log collection process."""

import os
from abc import ABC, abstractmethod


class QuickAction(ABC):
    """Base class for quick actions in the log collection process."""

    def __init__(self, params: dict, log_filename: str):
        self.params = params
        self.batches_root = params.get("batches_root", "")
        self.anomaly_interval = params.get("anomaly_interval", 1)
        self.log_filename = log_filename

    @abstractmethod
    def execute(self, batch_id: str) -> None:
        """Execute the (quick) log collection."""

    def get_output_dir(self, batch_id: str) -> str:
        """Return the output directory for the quick action."""
        log_path = os.path.join(self.batches_root, f"aod_{batch_id}", "quick", self.log_filename)
        return log_path
