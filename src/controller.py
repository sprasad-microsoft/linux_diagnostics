import threading
import queue
import subprocess
import os
import signal
import time
import traceback
import signal
import argparse

from shared_data import *
from ConfigManager import ConfigManager
from EventDispatcher import EventDispatcher
from AnomalyWatcher import AnomalyWatcher
from LogCollectorManager import LogCollectorManager
from LogCompressor import LogCompressor
from AuditLogger import AuditLogger
from SpaceWatcher import SpaceWatcher

class Controller:

    def __init__(self, config_path: str):
        self.stop_event = threading.Event()
        self.config = ConfigManager(config_path).data
        print("Parsed config file")
        import pprint
        pp = pprint.PrettyPrinter(indent=2)
        pp.pprint(self.config)
        self.threads = []
        self.eventQueue = queue.Queue()
        self.anomalyActionQueue = queue.Queue()
        self.archiveQueue = queue.Queue()
        self.auditQueue = queue.Queue()

    def _supervise_thread(self, name: str, target: callable, *args, **kwargs) -> None:
        def runner():
            while not self.stop_event.is_set():
                try:
                    target(*args, **kwargs)
                except Exception as e:
                    print(f"{name} died: {traceback.format_exc()}")
                    time.sleep(1)  # Wait before restarting
        t = threading.Thread(target=runner, name=name, daemon=True)
        t.start()
        print(f"Started thread {name} with ID {t.ident}")
        self.threads.append(t)

    def _supervise_process(self) -> None:
        while not self.stop_event.is_set():
            self._start_ebpf_process()
            while True:
                if self.stop_event.wait(timeout=1):
                    break
                if self.ebpf_process.poll() is not None:
                    print("eBPF process exited unexpectedly, restarting...")
                    break
            if self.stop_event.is_set():
                os.killpg(os.getpgid(self.ebpf_process.pid), signal.SIGINT)
                self.ebpf_process.wait(timeout=5)
                print("eBPF process stopped gracefully")
                break
            time.sleep(1)
      
    def _start_ebpf_process(self):
        wrapper_path = os.path.join(os.path.dirname(__file__), "pdeathsig_wrapper.py")
        ebpf_binary_path = os.path.join(os.path.dirname(__file__), "smbsloweraod")
        x, y = self._get_ebpf_args()
        self.ebpf_process = subprocess.Popen(
            ["python3", wrapper_path, ebpf_binary_path, "-m", str(x), "-c", y],
            preexec_fn=os.setsid
        )
        #for now im launching smbslower by default
        #later as per the config file, we shld launch the necessary tools
        print(f"Started new eBPF process with PID {self.ebpf_process.pid} and args: -m {x} -c {y}")

    def _get_ebpf_args(self):
        # Find the latency anomaly config
        latency_anomaly = None
        for anomaly in self.config.guardian.anomalies.values():
            if anomaly.type.lower() == "latency":
                latency_anomaly = anomaly
                break

        if latency_anomaly is None:
            raise RuntimeError("No latency anomaly config found!")

        # x: minimum of all thresholds (including default)
        thresholds = [v for v in latency_anomaly.track.values() if v is not None and v >= 0]
        if latency_anomaly.default_threshold_ms is not None:
            thresholds.append(latency_anomaly.default_threshold_ms)
        x = min(thresholds)

        # y: list of all SMB commands we want to track, as numbers, comma-separated
        smbcmds = [str(ALL_SMB_CMDS[cmd]) for cmd, v in latency_anomaly.track.items() if v is not None and v >= 0]
        y = ",".join(smbcmds)
        return x, y

    def stop(self) -> None:
        self.stop_event.set()

    def _shutdown(self) -> None:
        for thread in self.threads:
            thread.join(timeout=5)
            print(f"Thread {thread.name} with ID {thread.ident} has been shut down")
        print("Shutting down all components")
        # Clean up shared memory via EventDispatcher
        if hasattr(self, "event_dispatcher"):
            self.event_dispatcher.cleanup()
        if hasattr(self, "log_collector_manager"):
            self.log_collector_manager.stop()

    def run(self) -> None:

        process_thread = threading.Thread(target=self._supervise_process, name="ProcessSupervisor", daemon=True)
        process_thread.start()
        print(f"Started thread eBPFProcessSupervisor with ID {process_thread.ident}")
        self.threads.append(process_thread)
        
        self.event_dispatcher = EventDispatcher(self)
        self.log_collector_manager = LogCollectorManager(self)
        self._supervise_thread("EventDispatcher", self.event_dispatcher.run)
        self._supervise_thread("AnomalyWatcher", AnomalyWatcher(self).run)
        self._supervise_thread("LogCollector", self.log_collector_manager.run)
        self._supervise_thread("LogCompressor", LogCompressor(self).run)
        self._supervise_thread("AuditLogger", AuditLogger(self).run)
        self._supervise_thread("SpaceWatcher", SpaceWatcher(self).run)
        self.stop_event.wait()
        self._shutdown()

def main():
    
    # Check if script is running as root
    if os.geteuid() != 0:
        raise RuntimeError("Controller daemon must be run as root.")

    # add arguments later

    # Use the config path relative to this file, as in controller_draft.py
    config_path = os.path.join(os.path.dirname(__file__), "../config/config.yaml")
    controller = Controller(config_path)

    def handle_signal(signum, frame):
        print(f"Received signal {signum}, shutting down...")
        controller.stop()

    # should i specify this in the Controller constructor?
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    controller.run()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print("Fatal error in main():")
        traceback.print_exc()