from base.QuickAction import QuickAction

class CifsstatsQuickAction(QuickAction):
    def __init__(self, batches_root: str):
        """Args:
            batches_root (str): Root directory for log batches.
        """
        super().__init__(batches_root, "cifsstats.log")

    def get_command(self) -> list:
        return [
            "cat",
            "/proc/fs/cifs/Stats",
        ]
