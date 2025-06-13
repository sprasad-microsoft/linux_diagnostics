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
        #trying to ensure that we only delete directories created by AOD
        #for now we are assuming user wont create directories starting with "aod_"
        to_delete_batches = [d for d in self.batches_root.iterdir() if d.is_dir() and d.name.startswith("aod_") and d.stat().st_mtime < cutoff]
        if not to_delete_batches:
            print("[SpaceWatcher] No AOD batch entries to cleanup by age.")
            return
        deleted = 0
        for entry in to_delete_batches:
            try:
                shutil.rmtree(entry)
                deleted += 1
                print(f"[SpaceWatcher] Deleted old batch entry {entry}")
            except Exception as e:
                print(f"[SpaceWatcher] Failed to delete {entry}: {e}")
        print(f"[SpaceWatcher] Age-based cleanup complete. Deleted {deleted} batch entries.")

    def _get_completed_aod_batches(self):
        completed_batches = []
        in_progress_batches = []
        batch_size_map = {}
        for batch_dir in self.batches_root.iterdir():

            if not batch_dir.is_dir():
                batch_size_map[batch_dir] = batch_dir.stat().st_size
                continue

            batch_size_map[batch_dir] = sum(f.stat().st_size for f in batch_dir.glob('**/*') if f.is_file())
            
            if not batch_dir.name.startswith("aod_"):
                continue

            # Check quick/.IN_PROGRESS
            quick_dir = batch_dir / "quick"
            if quick_dir.exists() and (quick_dir / ".IN_PROGRESS").exists():
                print(f"[SpaceWatcher] Giving lower delete priority to {batch_dir} due to .IN_PROGRESS in quick directory")
                in_progress_batches.append(batch_dir)
                continue

            # Check live/<tool>/.IN_PROGRESS
            live_dir = batch_dir / "live"
            if live_dir.exists():
                in_progress_found = False
                for tool_dir in live_dir.iterdir():
                    if tool_dir.is_dir() and (tool_dir / ".IN_PROGRESS").exists():
                        print(f"[SpaceWatcher] Giving lower delete priority to {batch_dir} due to .IN_PROGRESS in live/{tool_dir.name} directory")
                        in_progress_found = True
                        break
                if in_progress_found:
                    in_progress_batches.append(batch_dir)
                    continue
            # If no .IN_PROGRESS found, add batch_dir
            completed_batches.append(batch_dir)
        return completed_batches, in_progress_batches, batch_size_map

    #rewrite so that u only delete directories created by AOD
    def cleanup_by_size(self) -> None:
        """Delete largest completed batch directories or files until total size is under max_size."""
        comp_batches, in_progress_batches, batch_size_map = self._get_completed_aod_batches()
        if not comp_batches and not in_progress_batches:
            print("[SpaceWatcher] No eligible batches to cleanup by size.")
            return
        comp_batches = np.array(comp_batches)
        batch_size_map = np.vectorize(batch_size_map.get)

        sorted_batches = comp_batches[np.argsort(-1*batch_size_map(comp_batches))]
        total_size = sum(f.stat().st_size for f in self.batches_root.glob('**/*') if f.is_file())
        max_bytes = self.max_size * 1024 * 1024
        print(f"[SpaceWatcher] Total size of batches: {total_size / (1024 * 1024):.2f} MB, max allowed: {self.max_size} MB")
        
        deleted = 0
        # first check if deleting completed batches suffices
        for batch in sorted_batches:
            if total_size <= max_bytes * .5:
                break
            batch_sz = batch_size_map(batch)
            try:
                shutil.rmtree(batch)
                total_size -= batch_sz
                deleted += 1
                print(f"[SpaceWatcher] Deleted batch {batch} ({batch_sz} bytes)")
            except Exception as e:
                print(f"[SpaceWatcher] Failed to delete {batch}: {e}")
        
        # if still above threshold, delete in-progress batches
        if total_size > max_bytes * .8:
            in_progress_batches = np.array(in_progress_batches)
            sorted_in_progress = in_progress_batches[np.argsort(-1*batch_size_map(in_progress_batches))]
            for batch in sorted_in_progress:
                if total_size <= max_bytes * .8:
                    break
                batch_sz = batch_size_map(batch)
                try:
                    shutil.rmtree(batch)
                    total_size -= batch_sz
                    deleted += 1
                    print(f"[SpaceWatcher] Deleted in-progress batch {batch} ({batch_sz} bytes)")
                except Exception as e:
                    print(f"[SpaceWatcher] Failed to delete in-progress {batch}: {e}")
    
        print(f"[SpaceWatcher] Size-based cleanup complete. Deleted {deleted} batches.")