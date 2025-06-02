import threading
import queue
import subprocess
import os
import signal
import time
import traceback
import yaml

class ConfigManager:
    def __init__(self, config_path):
        # Load YAML config from the given path
        with open(config_path, "r") as f:
            self.data = yaml.safe_load(f)

class EventDispatcher:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        while not self.controller.stop_event.is_set():
            time.sleep(1)  # Simulate polling
            event = {"event": "dummy_event"}
            self.controller.eventQueue.put(event)

class AnomalyWatcher:
    def __init__(self, controller):
        self.controller = controller
        self.interval = self.controller.config["watch_interval_sec"]

    def run(self):
        while not self.controller.stop_event.is_set():
            time.sleep(self.interval)
            try:
                event = self.controller.eventQueue.get(timeout=1)
                action = {"anomaly": "latency", "timestamp": time.time(), "event": event}
                self.controller.anomalyActionQueue.put(action)
            except queue.Empty:
                continue

class LogCollectorManager:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        while not self.controller.stop_event.is_set():
            try:
                action = self.controller.anomalyActionQueue.get(timeout=1)
                print(f"Collected logs for action: {action}")
                self.controller.anomalyActionQueue.task_done()
            except queue.Empty:
                continue

class LogCompressor:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        while not self.controller.stop_event.is_set():
            try:
                batch_id = self.controller.archiveQueue.get(timeout=1)
                print(f"Compressed logs for batch: {batch_id}")
                self.controller.archiveQueue.task_done()
            except queue.Empty:
                continue

class AuditLogger:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        while not self.controller.stop_event.is_set():
            try:
                record = self.controller.auditQueue.get(timeout=1)
                print(f"Logged audit record: {record}")
                self.controller.auditQueue.task_done()
            except queue.Empty:
                continue

class SpaceWatcher:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        while not self.controller.stop_event.is_set():
            time.sleep(self.controller.config["cleanup"]["cleanup_interval_sec"])
            print("Performed space cleanup")

class Controller:
    def __init__(self, config_path: str):
        self.stop_event = threading.Event()
        self.config = ConfigManager(config_path).data
        self.threads = []
        self.eventQueue = queue.Queue()
        self.anomalyActionQueue = queue.Queue()
        self.archiveQueue = queue.Queue()
        self.auditQueue = queue.Queue()

    def _supervise_thread(self, name: str, target: callable) -> None:
        def runner():
            while not self.stop_event.is_set():
                try:
                    target()
                except Exception as e:
                    print(f"{name} died: {traceback.format_exc()}")
                    time.sleep(1)  # Wait before restarting
        t = threading.Thread(target=runner, name=name, daemon=True)
        t.start()
        self.threads.append(t)

    def _supervise_process(self) -> None:
        while not self.stop_event.is_set():
            self._start_ebpf_process()  # Dummy implementation
            while True:
                if self.stop_event.wait(timeout=1):
                    break
                if self.ebpf_process.poll() is not None:
                    print("eBPF process exited unexpectedly, restarting...")
                    break
            if self.stop_event.is_set():
                os.killpg(os.getpgid(self.ebpf_process.pid), signal.SIGINT)
                self.ebpf_process.wait(timeout=5)
                break
            time.sleep(1)

    def _start_ebpf_process(self):
        self.ebpf_process = subprocess.Popen(["sleep", "100"], preexec_fn=os.setsid)

    def stop(self) -> None:
        self.stop_event.set()

    def _shutdown(self) -> None:
        for thread in self.threads:
            thread.join(timeout=5)
        print("Shutting down all components")

    def run(self) -> None:
        self._supervise_process()
        self._supervise_thread("EventDispatcher", EventDispatcher(self).run)
        self._supervise_thread("AnomalyWatcher", AnomalyWatcher(self).run)
        self._supervise_thread("LogCollector", LogCollectorManager(self).run)
        self._supervise_thread("LogCompressor", LogCompressor(self).run)
        self._supervise_thread("AuditLogger", AuditLogger(self).run)
        self._supervise_thread("SpaceWatcher", SpaceWatcher(self).run)
        self.stop_event.wait()
        self._shutdown()

# Test the Controller
if __name__ == "__main__":
    # Use the config path relative to this file, as in controller_draft.py
    config_path = os.path.join(os.path.dirname(__file__), "../config/config.yaml")
    controller = Controller(config_path)
    controller.run()
    time.sleep(10)  # Let it run for a while
    controller.stop()