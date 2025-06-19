"""Abstract base class for quick actions in the log collection process."""

import os
import subprocess
from abc import ABC, abstractmethod


class QuickAction(ABC):
    """Base class for quick actions in the log collection process."""

    def __init__(self, batches_root: str, log_filename: str):
        self.batches_root = batches_root
        self.log_filename = log_filename

    def get_output_dir(self, batch_id: str) -> str:
        """Return the output directory for the quick action."""
        log_path = os.path.join(self.batches_root, f"aod_{batch_id}", "quick", self.log_filename)
        return log_path

    @abstractmethod
    def get_command(self) -> list:
        """Return the command to run as a list."""

    def execute(self, batch_id: str) -> None:
        """Run process to collect logs."""
        output_path = self.get_output_dir(batch_id)
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                subprocess.run(
                    self.get_command(),
                    stdout=f,
                    check=True,
                )
        except subprocess.CalledProcessError as exc:
            print(f"[{self.__class__.__name__}] Error running command: {exc}")
        print(f"[{self.__class__.__name__}] Finished writing logs for batch {batch_id} at {output_path}")
