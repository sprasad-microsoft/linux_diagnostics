

from base.QuickAction import QuickAction

class JournalctlQuickAction(QuickAction):

    def __init__(self, batches_root: str, anomaly_interval: int = 1):
        """Args:
            batches_root (str): Root directory for log batches.
            anomaly_interval (int): Time interval in seconds to filter logs.
        """
        super().__init__(batches_root, "journalctl.log")
        self.anomaly_interval = anomaly_interval

    def get_command(self) -> list:
        return [
            "journalctl",
            "--since",
            f"{self.anomaly_interval} seconds ago",
        ]