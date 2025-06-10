import os
import time
import threading
import queue
import subprocess
import psutil
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod

BATCHES_ROOT = "/var/log/aod/batches"
PDEATHSIG_WRAPPER = os.path.join(os.path.dirname(__file__), "pdeathsig_wrapper.py")

class QuickAction(ABC):
    def __init__(self, params: dict):
        self.params = params

    @abstractmethod
    def execute(self, batch_id: str) -> None:
        """Execute the (quick) log collection."""

class JournalctlQuickAction(QuickAction):
    def execute(self, batch_id: str):
        output_path = os.path.join(BATCHES_ROOT, batch_id, "quick", "journalctl.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][journalctl] Collecting journalctl logs for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "journalctl", "-n", "100"],
                stdout=f
            )

class CifsstatsQuickAction(QuickAction):
    def execute(self, batch_id: str) -> None:
        output_path = os.path.join(BATCHES_ROOT, batch_id, "quick", "cifsstats.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][cifsstats] Collecting cifsstats logs for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "cat", "/proc/fs/cifs/Stats"],
                stdout=f
            )

class ToolManager(ABC):
    def __init__(self, controller, output_subdir: str = "live/tool", base_duration: int = 20, max_duration: int = 90):
        self.controller = controller 
        self.base_duration = base_duration
        self.max_duration = max_duration
        self.output_subdir = output_subdir
        self.lock = threading.Lock()
        self.end_time = {}
        self.max_end_time = {}
        self.proc = {}
        self.thread = {}

    def tool_name(self):
        # Extract tool name from output_subdir, e.g. live/tcpdump -> tcpdump
        return os.path.basename(self.output_subdir)

    def extend(self, batch_id: str) -> None:
        """Start or extend the live capture window."""
        with self.lock:
            now = time.time()
            if batch_id not in self.proc:
                print(f"[Log Collector][{self.tool_name()}] Starting new capture for batch {batch_id}")
                self.end_time[batch_id] = now + self.base_duration
                self.max_end_time[batch_id] = now + self.max_duration
                self._start(batch_id)
                return

            remaining = self.end_time[batch_id] - now
            proposed_end = self.end_time[batch_id] + self.base_duration
            if remaining < 10 and proposed_end <= self.max_end_time[batch_id]:
                print(f"[Log Collector][{self.tool_name()}] Extending capture for batch {batch_id} by {self.base_duration} seconds")
                self.end_time[batch_id] = proposed_end

    @abstractmethod
    def _build_command(self, batch_id: str) -> list:
        ...

    def _start(self, batch_id: str) -> None:
        output_path = os.path.join(BATCHES_ROOT, batch_id, self.output_subdir)
        os.makedirs(output_path, exist_ok=True)
        in_progress = os.path.join(output_path, ".IN_PROGRESS")
        with open(in_progress, "w") as f:
            f.write("running\n")
        cmd = self._build_command(batch_id)
        print(f"[Log Collector][{self.tool_name()}] Launching process for batch {batch_id}: {' '.join(cmd)}")
        self.proc[batch_id] = subprocess.Popen(cmd)
        self.thread[batch_id] = threading.Thread(target=self._monitor, args=(batch_id,), daemon=True)
        self.thread[batch_id].start()

    def _monitor(self, batch_id: str) -> None:
        print(f"[Log Collector][{self.tool_name()}] Monitoring batch {batch_id}")
        while time.time() < self.end_time[batch_id]:
            time.sleep(20)
        self._finalize(batch_id)

    def _finalize(self, batch_id: str) -> None:
        print(f"[Log Collector][{self.tool_name()}] Finalizing batch {batch_id}")
        if batch_id in self.proc:
            print(f"[Log Collector][{self.tool_name()}] Terminating process for batch {batch_id}")
            self.proc[batch_id].terminate()
            self.proc[batch_id].wait()
        output_path = os.path.join(BATCHES_ROOT, batch_id, self.output_subdir)
        in_progress = os.path.join(output_path, ".IN_PROGRESS")
        complete = os.path.join(output_path, ".COMPLETE")
        if os.path.exists(in_progress):
            os.rename(in_progress, complete)
            print(f"[Log Collector][{self.tool_name()}] Renamed {in_progress} to {complete}")
        self.controller.archiveQueue.put((batch_id, self.output_subdir, None))
        print(f"[Log Collector][{self.tool_name()}] Added batch {batch_id} to archive queue")

    def stop_all(self) -> None:
        print(f"[Log Collector][{self.tool_name()}] Stopping all batches")
        with self.lock:
            for batch_id in list(self.proc.keys()):
                print(f"[Log Collector][{self.tool_name()}] Terminating process for batch {batch_id}")
                self.proc[batch_id].terminate()
                self.proc[batch_id].wait()
            self.proc.clear()
            self.end_time.clear()
            self.max_end_time.clear()
        for thread in self.thread.values():
            if thread.is_alive():
                thread.join(timeout=1)
        self.thread.clear()

    def _can_extend(self, batch_id: str, now: float) -> bool:
        """Check CPU and if extending would stay within max duration."""
        for _ in range(3):
            cpu_idle = psutil.cpu_times_percent(interval=0.5).idle
            if cpu_idle > 20:
                break
            time.sleep(1)
        else:
            subprocess.run(["logger", "-p", "user.warning", f"Not enough CPU to start {self.__class__.__name__}"])
            print(f"[Log Collector][{self.tool_name()}] Not enough CPU to start or extend batch {batch_id}")
            return False

        if batch_id not in self.max_end_time:
            return True
        proposed_end = self.end_time[batch_id] + self.base_duration
        if proposed_end <= self.max_end_time[batch_id]:
            return True
        print(f"[Log Collector][{self.tool_name()}] Cannot extend batch {batch_id}: would exceed max duration")
        return False

class TcpdumpManager(ToolManager):
    def __init__(self, controller, output_subdir: str = "live/tcpdump", base_duration: int = 20, max_duration: int = 90):
        super().__init__(controller, output_subdir, base_duration, max_duration)

    def _build_command(self, batch_id: str) -> list:
        output_path = os.path.join(BATCHES_ROOT, batch_id, "live", "tcpdump", "tcpdump.1.pcap")
        return ["python3", PDEATHSIG_WRAPPER, "tcpdump", "-i", "any", "-w", output_path]

class TraceCmdManager(ToolManager):
    def __init__(self, controller, output_subdir: str = "live/trace", base_duration: int = 20, max_duration: int = 90):
        super().__init__(controller, output_subdir, base_duration, max_duration)

    def _build_command(self, batch_id: str) -> list:
        output_path = os.path.join(BATCHES_ROOT, batch_id, "live", "trace-cmd", "trace.dat")
        return ["python3", PDEATHSIG_WRAPPER, "trace-cmd", "record", "-o", output_path]

class LogCollectorManager:
    def __init__(self, controller):
        self.controller = controller
        self.quick_actions_pool = ThreadPoolExecutor(max_workers=4)
        self.tcpdump_manager = TcpdumpManager(controller,"live/tcpdump", 20, 90)
        self.trace_manager = TraceCmdManager(controller,"live/trace", 20, 90)
        self.anomaly_actions = self.set_anomaly_actions()

    def set_anomaly_actions(self):
        # change code to parse config file to fill these details later
        return {
            "latency": [JournalctlQuickAction({}), CifsstatsQuickAction({}), self.tcpdump_manager, self.trace_manager],
            "error": [CifsstatsQuickAction({}), self.trace_manager]
        }

    def _ensure_batch_dir(self, evt) -> str:
        batch_id = str(evt.get("batch_id", evt.get("timestamp", int(time.time()))))
        batch_dir = os.path.join(BATCHES_ROOT, batch_id)
        os.makedirs(batch_dir, exist_ok=True)
        print(f"[Log Collector][manager] Ensured batch directory exists: {batch_dir}")
        return batch_id

    def _log_to_journalctl(self, evt: dict) -> None:
        print(f"[Log Collector][manager] Logging anomaly to journalctl: {evt}")

    def run(self) -> None:
        print("[Log Collector][manager] LogCollectorManager started running")
        while not self.controller.stop_event.is_set():
            try:
                evt = self.controller.anomalyActionQueue.get(timeout=1)
            except queue.Empty:
                continue
            batch_id = self._ensure_batch_dir(evt)
            self._log_to_journalctl(evt)
            anomaly_type = (
                evt["anomaly"].name.lower()
                if hasattr(evt.get("anomaly"), "name")
                else str(evt.get("anomaly", "")).lower()
            )
            print(f"[Log Collector][manager] Handling anomaly type '{anomaly_type}' for batch {batch_id}")
            for action in self.anomaly_actions.get(anomaly_type, []):
                if isinstance(action, ToolManager):
                    print(f"[Log Collector][manager] Extending tool manager for {action.output_subdir} batch {batch_id}")
                    action.extend(batch_id)
                else:
                    print(f"[Log Collector][manager] Submitting quick action {action.__class__.__name__} for batch {batch_id}")
                    self.quick_actions_pool.submit(action.execute, batch_id)
            print(f"[Log Collector][manager] Adding quick actions for batch {batch_id} to archive queue")
            self.controller.archiveQueue.put((batch_id, "quick", None))
            self.controller.anomalyActionQueue.task_done()

    def stop(self) -> None:
        print("[Log Collector][manager] Stopping LogCollectorManager and all tool managers")
        self.quick_actions_pool.shutdown(wait=True)
        self.tcpdump_manager.stop_all()
        self.trace_manager.stop_all()