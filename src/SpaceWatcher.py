"""Space Watcher is responsible for monitoring disk space usage in the AOD output directory."""

import logging
import time
import os
import shutil
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)
SIZE_DELETE_THRESHOLD = 0.5

class SpaceWatcher:
    """Wake up every 10 minutes and check the size of the output dir. 
    If it grows over a certain threshold, clean up older logs to bring the usage down to a safe threshold. 
    Every N days, clean up log bundles older than N days."""

    def __init__(self, controller):
        """Initialize the SpaceWatcher."""
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
        
        # Metrics tracking
        if __debug__:
            self.cleanup_runs = 0
            self.total_files_deleted = 0
            self.total_space_freed_mb = 0
            logger.info("SpaceWatcher initialized: max_size=%dMB, max_age=%d days, cleanup_interval=%ds", 
                       self.max_total_log_suze_mb, self.max_log_age_days, self.cleanup_interval)

    def run(self) -> None:
        """Periodically checks disk space and triggers cleanup if needed."""
        if __debug__:
            logger.info("SpaceWatcher started running")
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
            logger.warning("Total log size %.2f MB exceeds max %d MB", 
                         total_size / (1024 * 1024), self.max_total_log_suze_mb)
            return True
        return False

    def cleanup_by_age(self) -> None:
        """Delete batch directories or files older than max_log_age_days days using numpy for efficiency."""
        cutoff = time.time() - self.max_log_age_days * 24 * 60 * 60
        entries = list(self.batches_dir.glob("aod_*"))
        if not entries:
            if __debug__:
                logger.debug("No AOD batch entries to cleanup by age")
            return

        # Filter entries that are older than the cutoffs
        entries = np.array(entries)
        to_delete = entries[np.array([e.stat().st_mtime for e in entries]) < cutoff]

        if len(to_delete) == 0:
            if __debug__:
                logger.debug("No AOD batch entries to cleanup by age")
            return

        if __debug__:
            deleted_count = 0
            space_freed_bytes = 0
            
        for entry in to_delete:
            try:
                if __debug__:
                    size = entry.stat().st_size if entry.is_file() else sum(f.stat().st_size for f in entry.glob("**/*") if f.is_file())
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
                if __debug__:
                    deleted_count += 1
                    space_freed_bytes += size
                    logger.debug("Deleted old batch entry %s (%.1f KB)", entry, size / 1024)
            except (FileNotFoundError, PermissionError, OSError) as e:
                logger.warning("Failed to delete %s: %s", entry, e)
        
        if __debug__:
            self.cleanup_runs += 1
            self.total_files_deleted += deleted_count
            self.total_space_freed_mb += space_freed_bytes / (1024 * 1024)
            logger.info("Age-based cleanup complete. Deleted %d batch entries (%.1f MB freed).", 
                       deleted_count, space_freed_bytes / (1024 * 1024))

    def cleanup_by_size(self) -> None:
        """Delete oldest files or directories starting with aod_ until total size is under max_total_log_suze_mb."""
        entries = list(self.batches_dir.glob("aod_*"))
        if not entries:
            if __debug__:
                logger.debug("No eligible AOD entries to cleanup by size")
            return

        # Sort entries by modification time (oldest first)
        entries = np.array(entries)
        entries = entries[np.argsort([e.stat().st_mtime for e in entries])]

        # Calculate sizes
        def entry_size(e):
            return e.stat().st_size if e.is_file() else sum(f.stat().st_size for f in e.glob("**/*") if f.is_file())

        total_size = sum(entry_size(e) for e in entries)
        max_allowed_bytes = self.max_total_log_suze_mb * 1024 * 1024
        if __debug__:
            logger.info("Total size of AOD entries: %.2f MB, max allowed: %d MB", 
                   total_size / (1024 * 1024), self.max_total_log_suze_mb)

        if __debug__:
            deleted_count = 0
            space_freed_bytes = 0
            
        for entry in entries:
            if total_size <= max_allowed_bytes * SIZE_DELETE_THRESHOLD:
                break
            size = entry_size(entry)
            try:
                shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
                total_size -= size
                if __debug__:
                    deleted_count += 1
                    space_freed_bytes += size
                    logger.debug("Deleted entry %s (%.1f KB)", entry, size / 1024)
            except (FileNotFoundError, PermissionError, OSError) as e:
                logger.warning("Failed to delete %s: %s", entry, e)

        if __debug__:
            self.cleanup_runs += 1
            self.total_files_deleted += deleted_count
            self.total_space_freed_mb += space_freed_bytes / (1024 * 1024)
            
            # Log comprehensive metrics every 5 cleanup runs
            if self.cleanup_runs % 5 == 0:
                logger.debug("SpaceWatcher metrics: runs=%d, files_deleted=%d, space_freed=%.1fMB", 
                           self.cleanup_runs, self.total_files_deleted, self.total_space_freed_mb)

            logger.info("Size-based cleanup complete. Deleted %d entries (%.1f MB freed). Total size now: %.2f MB", 
                       deleted_count, space_freed_bytes / (1024 * 1024), total_size / (1024 * 1024))
