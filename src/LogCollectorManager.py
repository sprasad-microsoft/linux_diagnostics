import os
import time
import threading
import queue
import subprocess
import psutil
import signal
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod

PDEATHSIG_WRAPPER = os.path.join(os.path.dirname(__file__), "pdeathsig_wrapper.py")

class QuickAction(ABC):
    def __init__(self, params: dict):
        self.params = params
        self.batches_root = params.get("batches_root", "")
        self.anomaly_interval = params.get("anomaly_interval", 1)

    @abstractmethod
    def execute(self, batch_id: str) -> None:
        """Execute the (quick) log collection."""

class JournalctlQuickAction(QuickAction):
    def execute(self, batch_id: str):
        output_path = os.path.join(self.batches_root, batch_id, "quick", "journalctl.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][journalctl] Collecting journalctl logs for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "journalctl", "--since", f"{self.anomaly_interval} seconds ago"],
                stdout=f
            )
        print(f"[Log Collector][journalctl] Finished writing journalctl logs for batch {batch_id} at {output_path}")

class CifsstatsQuickAction(QuickAction):
    def execute(self, batch_id: str) -> None:
        output_path = os.path.join(self.batches_root, batch_id, "quick", "cifsstats.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][cifsstats] Collecting cifsstats logs for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "cat", "/proc/fs/cifs/Stats"],
                stdout=f
            )
        print(f"[Log Collector][cifsstats] Finished writing cifsstats logs for batch {batch_id} at {output_path}")

class DmesgQuickAction(QuickAction):
    def execute(self, batch_id: str):
        output_path = os.path.join(self.batches_root, batch_id, "quick", "dmesg.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][dmesg] Collecting dmesg logs for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "journalctl", "-k", "--since", f"{self.anomaly_interval} seconds ago"],  # -k does what --dmesg does in newer systems and -k has better compatibility itseems
                stdout=f
            )
        print(f"[Log Collector][dmesg] Finished writing dmesg logs for batch {batch_id} at {output_path}")

class DebugDataQuickAction(QuickAction):
    def execute(self, batch_id: str):
        output_path = os.path.join(self.batches_root, batch_id, "quick", "Debugdata.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][debugdata] Collecting debug data for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "cat", "/proc/fs/cifs/DebugData"],  # Replace with actual debug data command
                stdout=f
            )
        print(f"[Log Collector][debugdata] Finished writing debug data for batch {batch_id} at {output_path}")

class MountsQuickAction(QuickAction):
    def execute(self, batch_id: str):
        output_path = os.path.join(self.batches_root, batch_id, "quick", "mounts.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][mounts] Collecting /proc/mounts for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "cat", "/proc/mounts"],
                stdout=f
            )
        print(f"[Log Collector][mounts] Finished writing mounts logs for batch {batch_id} at {output_path}")

class SmbinfoQuickAction(QuickAction):
    def execute(self, batch_id: str):
        output_path = os.path.join(self.batches_root, batch_id, "quick", "smbinfo.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][smbinfo] Collecting smbinfo for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "smbinfo", "-h", "filebasicinfo"],  # Replace with actual smbinfo command if needed, also i dont think there is any option to collect 1s ago stuff only
                stdout=f
            )
        print(f"[Log Collector][smbinfo] Finished writing smbinfo logs for batch {batch_id} at {output_path}")

class SysLogsQuickAction(QuickAction):
    def execute(self, batch_id: str):
        output_path = os.path.join(self.batches_root, batch_id, "quick", "syslogs.log")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        print(f"[Log Collector][syslogs] Collecting syslogs for batch {batch_id} at {output_path}")
        with open(output_path, "w") as f:
            subprocess.run(
                ["python3", PDEATHSIG_WRAPPER, "cat", "/var/log/syslog"],  # Adjust path as needed, this is for Debian/Ubuntu
                stdout=f
            )
        print(f"[Log Collector][syslogs] Finished writing syslogs for batch {batch_id} at {output_path}")

class ToolManager(ABC):
    def __init__(self, controller, batches_root, output_subdir: str = "live/tool", base_duration: int = 20, max_duration: int = 60):
        self.controller = controller
        self.batches_root = batches_root
        self.base_duration = base_duration
        self.max_duration = max_duration
        self.output_subdir = output_subdir
        self.lock = threading.Lock()
        self.end_time = 0
        self.max_end_time = 0
        self.proc = None
        self.thread = None
        self.running_batch_id = None

    def tool_name(self):
        # Extract tool name from output_subdir, e.g. live/tcpdump -> tcpdump
        return os.path.basename(self.output_subdir)

    def extend(self, batch_id: str) -> None:
        """Start or extend the live capture window."""
        if self._can_extend(batch_id):
            with self.lock:
                if self.proc is None:
                    self._start(batch_id)
                else: #create symlink
                    if self.end_time - time.time() < 10: 
                        self.end_time += self.base_duration
                    print(f"[Log Collector][{self.tool_name()}] Extending for batch {batch_id} end time by {self.base_duration} seconds")
                    self._create_symlink_to_running_batch(batch_id)
        
    @abstractmethod
    def _build_command(self, batch_id: str) -> list:
        ...

    def _start(self, batch_id: str) -> None:
        output_path = os.path.join(self.batches_root, batch_id, self.output_subdir)
        os.makedirs(output_path, exist_ok=True)
        in_progress = os.path.join(output_path, ".IN_PROGRESS")
        with open(in_progress, "w") as f:
            f.write("running\n")
        cmd = self._build_command(batch_id)
        cmd = ["python3", PDEATHSIG_WRAPPER] + cmd
        #VVVIMP use shld set end time before running the thread bcos monitor might check with endtime 0 and stop the process
        self.end_time = time.time() + self.base_duration
        self.max_end_time = time.time() + self.max_duration
        print(f"[Log Collector][{self.tool_name()}] Launching process for batch {batch_id}: {' '.join(cmd)}")
        try:
            # Capture stderr for debugging
            self.proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, preexec_fn=os.setsid)
        except Exception as e:
            print(f"[Log Collector][{self.tool_name()}] Failed to start process for batch {batch_id}: {e}")
            self._finalize(batch_id)
            return
        self.thread = threading.Thread(target=self._monitor, args=(batch_id,), daemon=True)
        self.thread.start()
        self.running_batch_id = batch_id

    def _create_symlink_to_running_batch(self, batch_id: str):
        """Create a symlink in the current batch's output dir pointing to the running batch's output dir."""
        if self.running_batch_id is None or self.running_batch_id == batch_id:
            print(f"[Log Collector][{self.tool_name()}] No other running batch to symlink for batch {batch_id}")
            return
        src = os.path.join(self.batches_root, self.running_batch_id, self.output_subdir)
        dst = os.path.join(self.batches_root, batch_id, self.output_subdir)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            if os.path.islink(dst) or os.path.exists(dst):
                os.remove(dst)
            os.symlink(src, dst)
            print(f"[Log Collector][{self.tool_name()}] Created symlink from {dst} to {src}")
        except Exception as e:
            print(f"[Log Collector][{self.tool_name()}] Failed to create symlink: {e}")        

    def _monitor(self, batch_id: str) -> None:
        print(f"[Log Collector][{self.tool_name()}] Monitoring batch {batch_id}")
        while time.time() < self.end_time:
            time.sleep(20)
        print(f"[Log Collector][{self.tool_name()}] Tring Tring! Time up")
        self._finalize(batch_id)

    def _terminate_proc(self) -> None:
        """Terminate the running process group and join the monitor thread."""
        if self.proc is not None:
            print(f"[Log Collector][{self.tool_name()}] Terminating process")
            os.killpg(os.getpgid(self.proc.pid), signal.SIGINT)
            self.proc.wait()
        self.proc = None
        self.end_time = 0
        self.max_end_time = 0
        if self.thread is not None and self.thread.is_alive():
            if threading.current_thread() != self.thread:
                self.thread.join(timeout=1)
        self.thread = None

    def _finalize(self, batch_id: str) -> None:
        print(f"[Log Collector][{self.tool_name()}] Finalizing batch {batch_id}")
        self._terminate_proc()
        output_path = os.path.join(self.batches_root, batch_id, self.output_subdir)
        in_progress = os.path.join(output_path, ".IN_PROGRESS")
        complete = os.path.join(output_path, ".COMPLETE")
        if os.path.exists(in_progress):
            os.rename(in_progress, complete)
            print(f"[Log Collector][{self.tool_name()}] Renamed {in_progress} to {complete}")
        self.controller.archiveQueue.put((batch_id, self.output_subdir, None))
        print(f"[Log Collector][{self.tool_name()}] Added batch {batch_id} to archive queue")
        print(f"[Log Collector][{self.tool_name()}] Finished writing logs for batch {batch_id} in {output_path}")
        
    def stop_all(self) -> None:
        print(f"[Log Collector][{self.tool_name()}] Stopping all batches")
        with self.lock:
            self._terminate_proc()

    #doesnt need batch_id param, only for logging i kept it
    def _can_extend(self, batch_id: str) -> bool:
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

        if self.proc is None:  # new process
            return True
        proposed_end = self.end_time + self.base_duration
        if proposed_end <= self.max_end_time:
            return True
        print(f"[Log Collector][{self.tool_name()}] Cannot extend batch {batch_id}: would exceed max duration")
        return False

class TcpdumpManager(ToolManager):
    def __init__(self, controller, batches_root: str, output_subdir: str = "live/tcpdump", base_duration: int = 20, max_duration: int = 90):
        super().__init__(controller, batches_root, output_subdir, base_duration, max_duration)

    def _build_command(self, batch_id: str) -> list:
        output_path = os.path.join(self.batches_root, batch_id, self.output_subdir, "tcpdump.pcap")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        return [
            "tcpdump",
            "-i", "eth0", #choose whichever interface you want
            "tcp", "port", "445",  # SMB port
            "-w", output_path
        ]

class TraceCmdManager(ToolManager):
    def __init__(self, controller, batches_root: str, output_subdir: str = "live/trace", base_duration: int = 20, max_duration: int = 90):
        super().__init__(controller, batches_root, output_subdir, base_duration, max_duration)

    def _build_command(self, batch_id: str) -> list:
        output_path = os.path.join(self.batches_root, batch_id, self.output_subdir, "trace.dat")
        return [
            "trace-cmd", "record",
            "-e", "sched_switch",
            "-e", "sched_wakeup",
            "-e", "sched_wakeup_new",
            "-e", "sched_process_exit",
            "-e", "block_rq_issue",
            "-e", "block_rq_complete",
            "-e", "block_rq_insert",
            "-e", "net_dev_queue",
            "-e", "netif_receive_skb",
            "-e", "net_dev_xmit",
            "-e", "net_dev_start_xmit",
            "-o", output_path
        ]

class LogCollectorManager:
    def __init__(self, controller):
        self.controller = controller
        self.aod_output_dir = getattr(self.controller.config, "aod_output_dir", "/var/log/aod")
        self.batches_root = os.path.join(self.aod_output_dir, "batches")
        self.anomaly_interval = getattr(self.controller.config, "watch_interval_sec", 1)
        self.quick_actions_pool = ThreadPoolExecutor(max_workers=4)
        self.tcpdump_manager = TcpdumpManager(controller, self.batches_root, "live/tcpdump", 20, 90)
        self.trace_manager = TraceCmdManager(controller, self.batches_root, "live/trace", 20, 90)
        self.params = { "batches_root": self.batches_root, "anomaly_interval": self.anomaly_interval }
        self.action_factory = {
            "journalctl": lambda: JournalctlQuickAction(self.params),
            "cifsstats": lambda: CifsstatsQuickAction(self.params),
            "tcpdump": lambda: self.tcpdump_manager,
            "trace-cmd": lambda: self.trace_manager,
            "dmesg": lambda: DmesgQuickAction(self.params),
            "debugdata": lambda: DebugDataQuickAction(self.params),
            "mounts": lambda: MountsQuickAction(self.params),
            "smbinfo": lambda: SmbinfoQuickAction(self.params),
            "syslogs": lambda: SysLogsQuickAction(self.params)
        }
        self.anomaly_actions = self.set_anomaly_actions()

    def set_anomaly_actions(self):
        # change code to parse config file to fill these details later
        all_actions = [factory() for factory in self.action_factory.values()]
        return {
            "latency": all_actions,
            "error": all_actions
        }

    def _ensure_batch_dir(self, evt) -> str:
        batch_id = str(evt.get("batch_id", evt.get("timestamp", int(time.time()))))
        batch_dir = os.path.join(self.batches_root, batch_id)
        os.makedirs(batch_dir, exist_ok=True)
        print(f"[Log Collector][manager] Ensured batch directory exists: {batch_dir}")
        return batch_id

    def _log_to_syslog(self, evt: dict) -> None:
        print(f"[Log Collector][manager] Logging anomaly to syslog: {evt}")

    def run(self) -> None:
        print("[Log Collector][manager] LogCollectorManager started running")
        while not self.controller.stop_event.is_set():
            try:
                print("[Log Collector][manager] Waiting for events in anomalyActionQueue")
                evt = self.controller.anomalyActionQueue.get()
            except queue.Empty:
                continue
            batch_id = self._ensure_batch_dir(evt)
            self._log_to_syslog(evt)
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