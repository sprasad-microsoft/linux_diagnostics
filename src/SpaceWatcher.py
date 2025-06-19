"""Space Watcher is responsible for monitoring disk space usage in the AOD output directory."""

import time
import os
import shutil
from pathlib import Path
import numpy as np

SIZE_DELETE_THRESHOLD = 0.5
IN_PROGRESS_DELETE_THRESHOLD = 0.8

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
        """Delete batch directories or files older than max_log_age_days days."""
        cutoff = time.time() - self.max_log_age_days * 24 * 60 * 60
        # trying to ensure that we only delete directories created by AOD
        # for now we are assuming user wont create directories starting with "aod_"
        old_batches_to_delete = [
            d
            for d in self.batches_dir.iterdir()
            if d.is_dir() and d.name.startswith("aod_") and d.stat().st_mtime < cutoff
        ]
        if not old_batches_to_delete:
            print("[SpaceWatcher] No AOD batch entries to cleanup by age.")
            return
        deleted_count = 0
        for entry in old_batches_to_delete:
            try:
                shutil.rmtree(entry)
                deleted_count += 1
                print(f"[SpaceWatcher] Deleted old batch entry {entry}")
            except (FileNotFoundError, PermissionError, OSError) as e:
                print(f"[SpaceWatcher] Failed to delete {entry}: {e}")
        print(f"[SpaceWatcher] Age-based cleanup complete. Deleted {deleted_count} batch entries.")

    def _get_completed_aod_batches(self):
        completed_batches = []
        in_progress_batches = []
        batch_size_map = {}
        batch_time_map = {}
        for batch_dir in self.batches_dir.iterdir():

            batch_time_map[batch_dir] = batch_dir.stat().st_mtime

            if not batch_dir.is_dir():
                batch_size_map[batch_dir] = batch_dir.stat().st_size
                continue

            batch_size_map[batch_dir] = sum(
                f.stat().st_size for f in batch_dir.glob("**/*") if f.is_file()
            )

            if not batch_dir.name.startswith("aod_"):
                continue

            # Check quick/.IN_PROGRESS
            quick_dir = batch_dir / "quick"
            if quick_dir.exists() and (quick_dir / ".IN_PROGRESS").exists():
                print(
                    f"[SpaceWatcher] Giving lower delete priority to {batch_dir} due to .IN_PROGRESS in quick directory"
                )
                in_progress_batches.append(batch_dir)
                continue

            # Check live/<tool>/.IN_PROGRESS
            live_dir = batch_dir / "live"
            if live_dir.exists():
                in_progress_found = False
                for tool_dir in live_dir.iterdir():
                    if tool_dir.is_dir() and (tool_dir / ".IN_PROGRESS").exists():
                        print(
                            f"[SpaceWatcher] Giving lower delete priority to {batch_dir} due to .IN_PROGRESS in live/{tool_dir.name} directory"
                        )
                        in_progress_found = True
                        break
                if in_progress_found:
                    in_progress_batches.append(batch_dir)
                    continue
            # If no .IN_PROGRESS found, add batch_dir
            completed_batches.append(batch_dir)
        return completed_batches, in_progress_batches, batch_size_map, batch_time_map

    # rewrite so that u only delete directories created by AOD
    def cleanup_by_size(self) -> None:
        """Delete oldest files first until total size
        is under max_total_log_suze_mb."""
        completed_batches, in_progress_batches, batch_size_map, batch_time_map = self._get_completed_aod_batches()
        if not completed_batches and not in_progress_batches:
            print("[SpaceWatcher] No eligible batches to cleanup by size.")
            return
        completed_batches = np.array(completed_batches)
        batch_size_map = np.vectorize(batch_size_map.get)
        batch_time_map = np.vectorize(batch_time_map.get)

        sorted_batches = completed_batches[np.argsort(batch_time_map(completed_batches))]
        total_size = sum(f.stat().st_size for f in self.batches_dir.glob("**/*") if f.is_file())
        max_allowed_bytes = self.max_total_log_suze_mb * 1024 * 1024
        print(
            f"[SpaceWatcher] Total size of batches: {total_size / (1024 * 1024):.2f} MB, max allowed: {self.max_total_log_suze_mb} MB"
        )

        deleted_count = 0
        # first check if deleting completed batches suffices
        for batch in sorted_batches:
            if total_size <= max_allowed_bytes * SIZE_DELETE_THRESHOLD:
                break
            batch_sz = batch_size_map(batch)
            try:
                shutil.rmtree(batch)
                total_size -= batch_sz
                deleted_count += 1
                #print(f"[SpaceWatcher] Deleted batch {batch} ({batch_sz} bytes)")
            except (FileNotFoundError, PermissionError, OSError) as e:
                print(f"[SpaceWatcher] Failed to delete {batch}: {e}")

        # if still above threshold, delete in-progress batches
        if total_size > max_allowed_bytes * IN_PROGRESS_DELETE_THRESHOLD:
            in_progress_batches = np.array(in_progress_batches)
            sorted_in_progress = in_progress_batches[
                np.argsort(-1 * batch_size_map(in_progress_batches))
            ]
            for batch in sorted_in_progress:
                if total_size <= max_allowed_bytes * IN_PROGRESS_DELETE_THRESHOLD:
                    break
                batch_sz = batch_size_map(batch)
                try:
                    shutil.rmtree(batch)
                    total_size -= batch_sz
                    deleted_count += 1
                    #print(f"[SpaceWatcher] Deleted in-progress batch {batch} ({batch_sz} bytes)")
                except (FileNotFoundError, PermissionError, OSError) as e:
                    print(f"[SpaceWatcher] Failed to delete {batch}: {e}")

        print(f"[SpaceWatcher] Size-based cleanup complete. Deleted {deleted_count} batches. Total size now: {total_size / (1024 * 1024):.2f} MB")
