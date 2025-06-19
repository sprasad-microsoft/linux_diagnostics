from base.QuickAction import QuickAction

class SmbinfoQuickAction(QuickAction):
    def __init__(self, batches_root: str):
        """Args:
            batches_root (str): Root directory for log batches.
        """
        super().__init__(batches_root, "smbinfo.log")

    def get_command(self) -> list:
        return [
            "smbinfo",
            "-h",
            "filebasicinfo",
        ]