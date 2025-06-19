"""Main controller module for the AODv2 service.

Responsible for orchestrating startup, configuration, process
supervision, and graceful shutdown of all service components.
"""

import threading
import queue
import subprocess
import os
import signal
from functools import partial
import time
import traceback

from shared_data import ALL_SMB_CMDS
from ConfigManager import ConfigManager
from EventDispatcher import EventDispatcher
from AnomalyWatcher import AnomalyWatcher
from LogCollectorManager import LogCollectorManager
from LogCompressor import LogCompressor
from AuditLogger import AuditLogger
from SpaceWatcher import SpaceWatcher


class Controller:
    """Main controller class for the AODv2 service."""

    def __init__(self, config_path: str):
        """Manages configuration, starts and supervises all service components,
        and coordinates graceful shutdown."""
        self.stop_event = threading.Event()
        self.config = ConfigManager(config_path).data
        self.threads = []
        self.eventQueue = queue.Queue()
        self.anomalyActionQueue = queue.Queue()
        self.archiveQueue = queue.Queue()
        self.auditQueue = queue.Queue()
        self.tool_processes = {}
        self.tool_starters = {
            "smbslower": self.start_smbsloweraod,
            # "smbiosnoop": self.start_smbiosnoop,
        }

        # Initialize all components
        self.event_dispatcher = EventDispatcher(self)
        self.log_collector_manager = LogCollectorManager(self)
        self.log_compressor = LogCompressor(self)
        self.audit_logger = AuditLogger(self)
        self.space_watcher = SpaceWatcher(self)
        self.anomaly_watcher = AnomalyWatcher(self)

    def _supervise_thread(self, thread_name: str, target: callable, *args, **kwargs) -> None:
        """Start and supervise a thread, restarting it if it dies
        unexpectedly."""

        def runner():
            while not self.stop_event.is_set():
                try:
                    target(*args, **kwargs)
                except RuntimeError:
                    print(f"{thread_name} died: {traceback.format_exc()}")
                    time.sleep(1)  # Wait before restarting

        t = threading.Thread(target=runner, name=thread_name, daemon=True)
        t.start()
        print(f"[Controller] Started thread {thread_name} with ID {t.ident}")
        self.threads.append(t)

    def _supervise_process(self, process_name: str, start_func: callable) -> None:
        """Supervise a process, restarting it if it exits unexpectedly."""
        while not self.stop_event.is_set():
            process = start_func()
            self.tool_processes[process_name] = process
            print(f"[Controller] Started {process_name} process with PID {process.pid}")
            while True:
                if self.stop_event.wait(timeout=1):
                    break
                if process.poll() is not None:
                    print(
                        f"[Controller] {process_name} process exited unexpectedly with code {process.returncode}, restarting..."
                    )
                    break
            if self.stop_event.is_set():
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGINT)
                    process.wait(timeout=5)
                    print(f"[Controller] {process_name} process stopped gracefully")
                except RuntimeError:
                    print(f"[Controller] {process_name} process did not stop gracefully")
                break
            time.sleep(1)

    def _get_smbsloweraod_args(self) -> tuple[int, str]:
        """Get arguments for the smbsloweraod process based on the latency
        anomaly config."""
        latency_anomaly = self.config.guardian.anomalies.get("latency")
        if latency_anomaly is None:
            return 10, list(ALL_SMB_CMDS.values())  # Default threshold is 10

        min_threshold = min(list(latency_anomaly.track.values()))

        # track_cmds: list of all SMB commands we want to track, as numbers, comma-separated
        smbcmds = [str(cmd_id) for cmd_id, threshold in latency_anomaly.track.items()]
        track_cmds = ",".join(smbcmds)
        return min_threshold, track_cmds

    def start_smbsloweraod(self) -> subprocess.Popen:
        """Start the smbsloweraod process and return the process object."""
        ebpf_binary_path = os.path.join(os.path.dirname(__file__), "bin", "smbsloweraod")
        min_threshold, track_cmds = self._get_smbsloweraod_args()
        return subprocess.Popen(
            [ebpf_binary_path, "-m", str(min_threshold), "-c", track_cmds],
            start_new_session=True,
        )

    def stop(self) -> None:
        """Signal all threads and processes to stop."""
        self.stop_event.set()

    def _shutdown(self) -> None:
        """Shutdown all threads and components gracefully."""

        # Unblock all queues to allow threads to exit
        self.eventQueue.put(None)  # Sentinel to stop EventDispatcher
        self.anomalyActionQueue.put(None)  # Sentinel to stop AnomalyWatcher
        self.archiveQueue.put(None)  # Sentinel to stop LogCompressor
        self.auditQueue.put(None)  # Sentinel to stop AuditLogger

        # Wait for all items to be processed
        self.eventQueue.join()
        self.anomalyActionQueue.join()
        self.archiveQueue.join()
        self.auditQueue.join()

        for thread in self.threads:
            thread.join(timeout=5)
            print(f"[Controller] Thread {thread.name} with ID {thread.ident} has been shut down")
        print("[Controller] Shutting down all components")

        if hasattr(self, "event_dispatcher"):
            self.event_dispatcher.cleanup()
        if hasattr(self, "log_collector_manager"):
            self.log_collector_manager.stop()
        # if hasattr(self, "space_watcher"):
        #     self.space_watcher.cleanup_by_size()

    def _extract_tools(self) -> set[str]:
        """Extract the set of ebpf tools to run from the config."""
        tool_names = set()
        for anomaly in self.config.guardian.anomalies.values():
            tool_names.add(anomaly.tool)
        return tool_names

    def run(self) -> None:
        """Start all supervisor threads and wait for shutdown."""
        tool_names = self._extract_tools()
        for tool_name in tool_names:
            start_func = self.tool_starters.get(tool_name)
            if start_func:
                t = threading.Thread(
                    target=self._supervise_process,
                    args=(tool_name, start_func),
                    name=f"{tool_name}_Supervisor",
                    daemon=True,
                )
                t.start()
                self.threads.append(t)
            else:
                print(f"Warning: No start function defined for tool '{tool_name}'")

        self._supervise_thread("EventDispatcher", self.event_dispatcher.run)
        self._supervise_thread("AnomalyWatcher", self.anomaly_watcher.run)
        self._supervise_thread("LogCollector", self.log_collector_manager.run)
        self._supervise_thread("LogCompressor", self.log_compressor.run)
        self._supervise_thread("AuditLogger", self.audit_logger.run)
        self._supervise_thread("SpaceWatcher", self.space_watcher.run)
        self.stop_event.wait()
        self._shutdown()


def handle_signal(controller, signum, frame):
    """Handle termination signals to gracefully shut down the controller."""
    print(f"Received signal {signum}, shutting down...")
    controller.stop()


def main():
    """Main entry point for the AODv2 controller daemon."""

    # Check if script is running as root
    if os.geteuid() != 0:
        raise RuntimeError("Controller daemon must be run as root.")

    # add arguments later

    # Use the config path relative to this file, as in controller_draft.py
    config_path = os.path.join(os.path.dirname(__file__), "../config/config.yaml")
    controller = Controller(config_path)
    signal.signal(signal.SIGTERM, partial(handle_signal, controller))
    signal.signal(signal.SIGINT, partial(handle_signal, controller))
    controller.run()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Fatal error in main():", e)
        traceback.print_exc()
