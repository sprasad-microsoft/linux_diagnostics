"""Space Watcher is responsible for monitoring disk space usage in the AOD output directory."""

import time
import os
import shutil
from pathlib import Path
import numpy as np

SIZE_DELETE_THRESHOLD = 0.5

class SpaceWatcher:
    """Wake up every 10 minutes and check the size of the output dir. 
    If it grows over a certain threshold, clean up older logs to bring the usage down to a safe threshold. 
    Every N days, clean up log bundles older than N days."""

    def __init__(self, controller):
        self.controller = controller
        cleanup_config = controller.config.cleanup
        self.max_log_age_days = cleanup_config.get("max_log_age_days", 2)  # Default to 2 days if not set
        self.max_total_log_suze_mb = cleanup_config.get("max_total_log_size_mb", 200)  # Default to 200 MB if not set
        self.cleanup_interval = cleanup_config.get("cleanup_interval_sec", 60)  # Default to 60 sec if not set
        self.aod_output_dir = cleanup_config.get(
            "aod_output_dir", "/var/log/aod"
        )  # Default to /var/log/aod if not set
        self.batches_dir = Path(os.path.join(self.aod_output_dir, "batches"))
        self.last_full_cleanup = time.time()

    def run(self) -> None:
        """Periodically checks disk space and triggers cleanup if needed."""
        print("SpaceWatcher started running")
        while not self.controller.stop_event.is_set():
            if self._check_space():
                self.cleanup_by_size()
            if self._full_cleanup_needed():
                self.cleanup_by_age()
            time.sleep(self.cleanup_interval)

    def _full_cleanup_needed(self) -> bool:
        """Check if current time  > last_full_cleanup + max_log_age_days."""
        current_time = time.time()
        if (
            current_time - self.last_full_cleanup > self.max_log_age_days * 24 * 60 * 60
        ):  # Convert days to seconds
            self.last_full_cleanup = current_time
            return True
        return False

    def _check_space(self) -> bool:
        """Check if disk space is below a threshold using pathlib."""
        total_size = sum(f.stat().st_size for f in self.batches_dir.glob("**/*") if f.is_file())
        if total_size > self.max_total_log_suze_mb * 1024 * 1024:  # Convert MB to bytes
            print(
                f"[SpaceWatcher] Total log size {total_size / (1024 * 1024):.2f} MB exceeds max {self.max_total_log_suze_mb} MB"
            )
            return True
        return False

    def cleanup_by_age(self) -> None:
        """Delete batch directories or files older than max_log_age_days days using numpy for efficiency."""
        cutoff = time.time() - self.max_log_age_days * 24 * 60 * 60
        entries = list(self.batches_dir.glob("aod_*"))
        if not entries:
            print("[SpaceWatcher] No AOD batch entries to cleanup by age.")
            return

        # Filter entries that are older than the cutoffs
        entries = np.array(entries)
        to_delete = entries[np.array([e.stat().st_mtime for e in entries]) < cutoff]

        if len(to_delete) == 0:
            print("[SpaceWatcher] No AOD batch entries to cleanup by age.")
            return

        deleted_count = 0
        for entry in to_delete:
            try:
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
                deleted_count += 1
                print(f"[SpaceWatcher] Deleted old batch entry {entry}")
            except (FileNotFoundError, PermissionError, OSError) as e:
                print(f"[SpaceWatcher] Failed to delete {entry}: {e}")
        print(f"[SpaceWatcher] Age-based cleanup complete. Deleted {deleted_count} batch entries.")

    def cleanup_by_size(self) -> None:
        """Delete oldest files or directories starting with aod_ until total size is under max_total_log_suze_mb."""
        entries = list(self.batches_dir.glob("aod_*"))
        if not entries:
            print("[SpaceWatcher] No eligible AOD entries to cleanup by size.")
            return

        # Sort entries by modification time (oldest first)
        entries = np.array(entries)
        entries = entries[np.argsort([e.stat().st_mtime for e in entries])]

        # Calculate sizes
        def entry_size(e):
            return e.stat().st_size if e.is_file() else sum(f.stat().st_size for f in e.glob("**/*") if f.is_file())

        total_size = sum(entry_size(e) for e in entries)
        max_allowed_bytes = self.max_total_log_suze_mb * 1024 * 1024
        print(
            f"[SpaceWatcher] Total size of AOD entries: {total_size / (1024 * 1024):.2f} MB, max allowed: {self.max_total_log_suze_mb} MB"
        )

        deleted_count = 0
        for entry in entries:
            if total_size <= max_allowed_bytes * SIZE_DELETE_THRESHOLD:
                break
            size = entry_size(entry)
            try:
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
                total_size -= size
                deleted_count += 1
                print(f"[SpaceWatcher] Deleted entry {entry} ({size / 1024:.1f} KB)")
            except (FileNotFoundError, PermissionError, OSError) as e:
                print(f"[SpaceWatcher] Failed to delete {entry}: {e}")

        print(f"[SpaceWatcher] Size-based cleanup complete. Deleted {deleted_count} entries. Total size now: {total_size / (1024 * 1024):.2f} MB")
