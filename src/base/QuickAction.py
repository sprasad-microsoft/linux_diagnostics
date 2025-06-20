"""Abstract base class for quick actions in the log collection process."""

import asyncio
from pathlib import Path
import os
from abc import ABC, abstractmethod


class QuickAction(ABC):
    """Base class for quick actions in the log collection process."""

    def __init__(self, batches_root: str, log_filename: str):
        self.batches_root = batches_root
        self.log_filename = log_filename

    def get_output_path(self, batch_id: str) -> str:
        """Return the output path for the quick action."""
        return os.path.join(self.batches_root, f"aod_quick_{batch_id}", self.log_filename)

    def get_output_dir(self, batch_id: str) -> str:
        """Return the output directory for the quick action."""
        return os.path.join(self.batches_root, f"aod_quick_{batch_id}")

    @abstractmethod
    def get_command(self) -> tuple[list[str], str]:
        """Return the command to run as a list.
        FOR CAT CMDS, RETURN A LIST OF SIZE 2: ["cat", "/path/to/file"]"""

    async def execute(self, batch_id: str) -> None:
        """Run process to collect logs."""
        output_path = self.get_output_path(batch_id)
        cmd, cmd_type = self.get_command()
        if cmd_type == "cat":
            # Expecting: ["cat", "/path/to/file"]
            _, in_path = cmd
            await self.collect_cat_output(in_path, output_path)
        elif cmd_type == "cmd":
            await self.collect_cmd_output(cmd, output_path)


    async def collect_cat_output(self, in_path: str, out_path: str) -> None:
        in_path = Path(in_path)
        out_path = Path(out_path)
        print(f"Collecting proc fs output from: {in_path}")
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Error creating directory {out_path.parent}: {e}")
            return
        data = in_path.read_bytes()
        out_path.write_bytes(data)
        print(f"Output written to: {out_path}")

    async def collect_cmd_output(self, cmd: list, out_path: str) -> None:
        out_path = Path(out_path)
        print(f"Collecting command output for: {cmd}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
        except Exception as e:
            print(f"Error executing command '{cmd}': {e}")
            return
        stdout, _ = await proc.communicate()
        if stdout:
            out_path.write_bytes(stdout)
        print(f"Command output written to: {out_path}")
