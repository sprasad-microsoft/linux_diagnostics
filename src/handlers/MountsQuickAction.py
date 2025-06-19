from base.QuickAction import QuickAction

class MountsQuickAction(QuickAction):
    def __init__(self, batches_root: str):
        """Args:
            batches_root (str): Root directory for log batches.
        """
        super().__init__(batches_root, "mounts.log")

    def get_command(self) -> list:
        return [
            "cat",
            "/proc/mounts",
        ]