import os
import time
import threading
import queue
import subprocess
import psutil
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod

class QuickAction(ABC):
    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def execute(self, batch_id: str) -> None:
        """Execute the (quick) log collection."""

class JournalctlQuickAction(QuickAction):
    def execute(self, batch_id: str):
        # Example: collect journalctl logs for the batch
        output_path = f"batches/{batch_id}/journalctl.log"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            subprocess.run(["journalctl", "-n", "100"], stdout=f)

class CifsstatsQuickAction(QuickAction):
    def execute(self, batch_id: str) -> None:
        output_path = f"batches/{batch_id}/cifsstats.log"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            subprocess.run(["cat", "/proc/fs/cifs/Stats"], stdout=f)

class ToolManager(ABC):
    def __init__(self, output_subdir: str = "live/tool", base_duration: int = 20, max_duration: int = 90):
        self.base_duration = base_duration
        self.max_duration = max_duration
        self.output_subdir = output_subdir
        self.lock = threading.Lock()
        self.end_times = {}
        self.proc = {}
        self.thread = {}

    def extend(self, batch_id: str) -> None:
        """Start or extend the live capture window."""
        with self.lock:
            now = time.time()
            if batch_id not in self.end_times:
                self.end_times[batch_id] = now + self.base_duration
                self._start(batch_id)
            else:
                # Only extend if within max_duration
                max_end = self.end_times[batch_id] + self.base_duration
                if max_end - now <= self.max_duration:
                    self.end_times[batch_id] = min(max_end, now + self.base_duration)

    @abstractmethod
    def _build_command(self, batch_id: str) -> list:
        ...

    def _start(self, batch_id: str) -> None:
        output_path = os.path.join("batches", batch_id, self.output_subdir)
        os.makedirs(output_path, exist_ok=True)
        in_progress = os.path.join(output_path, ".IN_PROGRESS")
        with open(in_progress, "w") as f:
            f.write("running\n")
        cmd = self._build_command(batch_id)
        self.proc[batch_id] = subprocess.Popen(cmd)
        self.thread[batch_id] = threading.Thread(target=self._monitor, args=(batch_id,), daemon=True)
        self.thread[batch_id].start()

    def _monitor(self, batch_id: str) -> None:
        # Wait until end_time, then finalize
        while time.time() < self.end_times[batch_id]:
            time.sleep(1)
        self._finalize(batch_id)

    def _finalize(self, batch_id: str) -> None:
        # ... terminate process ...
        output_path = os.path.join("batches", batch_id, self.output_subdir)
        in_progress = os.path.join(output_path, ".IN_PROGRESS")
        complete = os.path.join(output_path, ".COMPLETE")
        if os.path.exists(in_progress):
            os.rename(in_progress, complete)
        # Add to compression queue
        self.controller.archiveQueue.put((batch_id, self.output_subdir, None))

    def stop_all(self) -> None:
        with self.lock:
            for batch_id in list(self.proc.keys()):
                self.proc[batch_id].terminate()
                self.proc[batch_id].wait()
            self.proc.clear()
            self.end_times.clear()

    def _can_extend(self) -> bool:
        # Check if system has enough idle CPU (e.g., at least 20% idle)
        for _ in range(3):
            cpu_idle = psutil.cpu_times_percent(interval=0.5).idle
            if cpu_idle > 20:
                return True
            time.sleep(1)
        # Log warning if not enough CPU
        subprocess.run(["logger", "-p", "user.warning", f"Not enough CPU to start {self.__class__.__name__}"])
        return False

class TcpdumpManager(ToolManager):
    def _build_command(self, batch_id: str) -> list:
        output_path = os.path.join("batches", batch_id, self.output_subdir, "tcpdump.pcap")
        return ["tcpdump", "-i", "any", "-w", output_path]

class TraceCmdManager(ToolManager):
    def _build_command(self, batch_id: str) -> list:
        output_path = os.path.join("batches", batch_id, self.output_subdir, "trace.dat")
        return ["trace-cmd", "record", "-o", output_path]

class LogCollectionManager:
    def __init__(self, controller):
        self.controller = controller
        self.quick_actions_pool = ThreadPoolExecutor(max_workers=4)
        self.tcpdump_manager = TcpdumpManager("live/tcpdump", 20, 90)
        self.trace_manager = TraceCmdManager("live/trace", 20, 90)
        # Example: map anomaly_type to actions
        self.anomaly_actions = {
            "latency": [JournalctlQuickAction({}), self.tcpdump_manager],
            "error": [CifsstatsQuickAction({}), self.trace_manager]
        }

    def _ensure_batch_dir(self, evt) -> str:
        batch_id = evt.get("batch_id", str(int(time.time())))
        batch_dir = os.path.join("batches", batch_id)
        os.makedirs(batch_dir, exist_ok=True)
        return batch_id

    def _log_to_journalctl(self, evt: dict) -> None:
        # Placeholder: log to journalctl
        print(f"Logging anomaly to journalctl: {evt}")

    def run(self) -> None:
        print("LogCollectorManager started running")
        while not self.controller.stop_event.is_set():
            try:
                evt = self.controller.anomalyActionQueue.get(timeout=1)
                batch_id = self._ensure_batch_dir(evt)
                self._log_to_journalctl(evt)
                for action in self.anomaly_actions.get(evt["anomaly_type"], []):
                    if isinstance(action, ToolManager):
                        action.extend(batch_id)
                    else:
                        self.quick_actions_pool.submit(action.execute, batch_id)
                self.controller.archiveQueue.put((batch_id, "quick", None))
                self.controller.anomalyActionQueue.task_done()
            except queue.Empty:
                continue

    def stop(self) -> None:
        self.quick_actions_pool.shutdown(wait=True)
        self.tcpdump_manager.stop_all()
        self.trace_manager.stop_all()