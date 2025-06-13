import time
import os
from pathlib import Path
import numpy as np
import shutil

class SpaceWatcher:
    def __init__(self, controller):
        self.controller = controller
        cfg = controller.config.cleanup
        print(f"[SpaceWatcher] Initializing with config: {cfg}")
        self.max_age = cfg.get("max_log_age_days", 2)  # Default to 2 days if not set
        self.max_size = cfg.get("max_total_log_size_mb", 200)  # Default to 200 MB if not set
        self.cleanup_interval = cfg.get("cleanup_interval_sec", 60)  # Default to 60 sec if not set
        self.aod_output_dir = cfg.get("aod_output_dir", "/var/log/aod")  # Default to /var/log/aod if not set
        print(f"[SpaceWatcher] Initializing with max_age={self.max_age} days, max_size={self.max_size} MB, interval={self.cleanup_interval} sec")
        self.batches_root = Path(os.path.join(self.aod_output_dir, "batches"))
        self.last_full_cleanup = time.time()

    def run(self) -> None:
        print("SpaceWatcher started running")
        while not self.controller.stop_event.is_set():
            print("[SpaceWatcher] Checking disk space and cleanup needs...")
            if self._check_space():
                self.cleanup_by_size()
            elif self._full_cleanup_needed():
                self.cleanup_by_age()
            time.sleep(self.cleanup_interval)

    def _full_cleanup_needed(self) -> bool:
        """Check if current time  > last_full_cleanup + max_age"""
        current_time = time.time()
        if current_time - self.last_full_cleanup > self.max_age * 24 * 60 * 60:  # Convert days to seconds
            self.last_full_cleanup = current_time
            return True
        return False

    def _check_space(self) -> bool:
        """Check if disk space is below a threshold using pathlib."""
        total_size = sum(f.stat().st_size for f in self.batches_root.glob('**/*') if f.is_file())
        if total_size > self.max_size * 1024 * 1024:  # Convert MB to bytes
            print(f"[SpaceWatcher] Total log size {total_size / (1024 * 1024):.2f} MB exceeds max {self.max_size} MB")
            return True
        return False

    def cleanup_by_age(self) -> None:
        """Delete batch directories or files older than max_age days."""
        cutoff = time.time() - self.max_age * 24 * 60 * 60
        batches = [d for d in self.batches_root.iterdir()]
        if not batches:
            print("[SpaceWatcher] No batch entries to cleanup by age.")
            return
        batches = np.array(batches)
        mtimes = np.array([b.stat().st_mtime for b in batches])
        to_delete = batches[mtimes < cutoff]
        deleted = 0
        for entry in to_delete:
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                deleted += 1
                print(f"[SpaceWatcher] Deleted old batch entry {entry}")
            except Exception as e:
                print(f"[SpaceWatcher] Failed to delete {entry}: {e}")
        print(f"[SpaceWatcher] Age-based cleanup complete. Deleted {deleted} batch entries.")
        
    def _get_completed_batches(self):
        completed_batches = []
        for batch_dir in self.batches_root.iterdir():
            if not batch_dir.is_dir():
                completed_batches.append(batch_dir)
                continue
            # Check quick/.IN_PROGRESS
            quick_dir = batch_dir / "quick"
            if quick_dir.exists() and (quick_dir / ".IN_PROGRESS").exists():
                print(f"[SpaceWatcher] Skipping {batch_dir} due to .IN_PROGRESS in quick directory")
                continue
            # Check live/<tool>/.IN_PROGRESS
            live_dir = batch_dir / "live"
            if live_dir.exists():
                in_progress_found = False
                for tool_dir in live_dir.iterdir():
                    if tool_dir.is_dir() and (tool_dir / ".IN_PROGRESS").exists():
                        print(f"[SpaceWatcher] Skipping {batch_dir} due to .IN_PROGRESS in live/{tool_dir.name} directory")
                        in_progress_found = True
                        break
                if in_progress_found:
                    continue
            # If no .IN_PROGRESS found, add batch_dir
            completed_batches.append(batch_dir)
        return completed_batches

    def cleanup_by_size(self) -> None:
        """Delete largest completed batch directories or files until total size is under max_size."""
        batches = self._get_completed_batches()
        if not batches:
            print("[SpaceWatcher] No eligible batches to cleanup by size.")
            return
        batches = np.array(batches)
        # Calculate size for each batch (directory or file)
        def batch_size(b):
            if b.is_dir():
                return sum(f.stat().st_size for f in b.glob('**/*') if f.is_file())
            else:
                return b.stat().st_size
        sizes = np.array([batch_size(b) for b in batches])
        sorted_indices = np.argsort(-sizes)  # Largest first
        total_size = sum(f.stat().st_size for f in self.batches_root.glob('**/*') if f.is_file())
        max_bytes = self.max_size * 1024 * 1024
        print(f"[SpaceWatcher] Total size of batches: {total_size / (1024 * 1024):.2f} MB, max allowed: {self.max_size} MB")
        deleted = 0
        for idx in sorted_indices:
            if total_size <= max_bytes / 2:
                break
            batch = batches[idx]
            batch_sz = sizes[idx]
            try:
                if batch.is_dir():
                    shutil.rmtree(batch)
                else:
                    batch.unlink()
                total_size -= batch_sz
                deleted += 1
                print(f"[SpaceWatcher] Deleted batch {batch} ({batch_sz} bytes)")
            except Exception as e:
                print(f"[SpaceWatcher] Failed to delete {batch}: {e}")
        print(f"[SpaceWatcher] Size-based cleanup complete. Deleted {deleted} batches.")