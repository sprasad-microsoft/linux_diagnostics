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
import ctypes
import ctypes.util
import logging
import syslog


from shared_data import ALL_SMB_CMDS
from ConfigManager import ConfigManager
from EventDispatcher import EventDispatcher
from AnomalyWatcher import AnomalyWatcher
from LogCollector import LogCollector
from SpaceWatcher import SpaceWatcher
from utils.pdeathsig_wrapper import pdeathsig_preexec

logger = logging.getLogger(__name__)


def set_thread_name(name):
    """Set thread name visible in htop when pressing H to show threads."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        # Limit name to 15 characters (Linux kernel limit)
        name = name[:15].encode('utf-8')
        libc.prctl(15, name, 0, 0, 0)  # PR_SET_NAME = 15
    except Exception:
        pass


class Controller:
    """Main controller class for the AODv2 service."""

    def __init__(self, config_path: str):
        """Manages configuration, starts and supervises all service components,
        and coordinates graceful shutdown."""

        if __debug__:
            logger.info("Initializing Controller with config: %s", config_path)
        self.stop_event = threading.Event()
        self.config = ConfigManager(config_path).data
        self.threads = []
        
        # Metrics tracking
        if __debug__:
            self.thread_restarts = 0
            self.process_restarts = 0
        self.eventQueue = queue.Queue()
        self.anomalyActionQueue = queue.Queue()
        self.tool_processes = {}
        self.tool_cmd_builders = {
            "smbslower": self._get_smbsloweraod_cmd,
            # "smbiosnoop": self._get_smbiosnoop_cmd,
        }

        # Initialize all components
        if __debug__:
            logger.info("Initializing service components")
        self.event_dispatcher = EventDispatcher(self)
        self.anomaly_watcher = AnomalyWatcher(self)
        self.log_collector_manager = LogCollector(self)
        self.space_watcher = SpaceWatcher(self)
        if __debug__:
            logger.info("Controller initialization complete")

    def _supervise_thread(self, thread_name: str, target: callable, *args, **kwargs) -> None:
        """Start and supervise a thread, restarting it if it dies
        unexpectedly."""

        def runner():
            set_thread_name(thread_name) #only to view thread name in top
            while not self.stop_event.is_set():
                try:
                    target(*args, **kwargs)
                except Exception as e:
                    logger.error("%s thread died unexpectedly: %s", thread_name, e)
                    if __debug__:
                        logger.debug("Full traceback:", exc_info=True)
                        self.thread_restarts += 1
                    time.sleep(1)  # Wait before restarting
                    if __debug__:
                        logger.info("Restarting %s thread", thread_name)
                    syslog.syslog(syslog.LOG_WARNING, f"AOD component {thread_name} restarted due to unexpected exit")

        t = threading.Thread(target=runner, name=thread_name, daemon=True)
        t.start()
        if __debug__:
            logger.info("Started thread %s with ID %d", thread_name, t.ident)
        self.threads.append(t)

    def _supervise_process(self, process_name: str, cmd_builder: callable) -> None:
        """Supervise a process, restarting it if it exits unexpectedly."""
        set_thread_name("ProcessSupervisor") #only to view thread name in top
        while not self.stop_event.is_set():
            cmd = cmd_builder()
            process = subprocess.Popen(
                cmd,
                start_new_session=True,
                preexec_fn=pdeathsig_preexec
            )
            self.tool_processes[process_name] = process
            if __debug__:
                logger.info("Started %s process with PID %d", process_name, process.pid)
            while True:
                if self.stop_event.wait(timeout=1):
                    break
                if process.poll() is not None:
                    logger.warning("%s process exited unexpectedly with code %d, restarting...", 
                                 process_name, process.returncode)
                    if __debug__:
                        self.process_restarts += 1
                    syslog.syslog(syslog.LOG_WARNING, f"AOD component {process_name} restarted due to unexpected exit")
                    break
            if self.stop_event.is_set():
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGINT)
                    process.wait(timeout=5)
                    if __debug__:
                        logger.info("%s process stopped gracefully", process_name)
                except RuntimeError:
                    logger.warning("%s process did not stop gracefully", process_name)
                break
            time.sleep(1)

    def _get_smbsloweraod_cmd(self) -> list[str]:
        """Get command array for the smbsloweraod process based on the latency
        anomaly config."""
        latency_anomaly = self.config.guardian.anomalies.get("latency")
        if latency_anomaly is None:
            min_threshold = 10
            track_cmds = ",".join(str(cmd_id) for cmd_id in ALL_SMB_CMDS.keys())
        else:
            min_threshold = min(list(latency_anomaly.track.values()))
            # track_cmds: list of all SMB commands we want to track, as numbers, comma-separated
            smbcmds = [str(cmd_id) for cmd_id, threshold in latency_anomaly.track.items()]
            track_cmds = ",".join(smbcmds)
        
        ebpf_binary_path = os.path.join(os.path.dirname(__file__), "bin", "smbsloweraod")
        return [ebpf_binary_path, "-m", str(min_threshold), "-c", track_cmds]

    def stop(self) -> None:
        """Signal all threads and processes to stop."""
        self.stop_event.set()

    def _shutdown(self) -> None:
        """Shutdown all threads and components gracefully."""

        # Wait for all queues to be processed
        self.eventQueue.join()
        self.anomalyActionQueue.join()

        for thread in self.threads:
            thread.join(timeout=5)
            if __debug__:
                logger.info("Thread %s with ID %d has been shut down", thread.name, thread.ident)
                logger.info("Shutting down all components")

        if hasattr(self, "event_dispatcher"):
            self.event_dispatcher.cleanup()
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
        if __debug__:
            logger.info("Starting AOD service")
        set_thread_name("Controller") #only to view thread name in top
        tool_names = self._extract_tools()
        if __debug__:
            logger.info("Starting tools: %s", tool_names)
        for tool_name in tool_names:
            cmd_builder = self.tool_cmd_builders.get(tool_name)
            if cmd_builder:
                t = threading.Thread(
                    target=self._supervise_process,
                    args=(tool_name, cmd_builder),
                    name=f"{tool_name}_Supervisor",
                    daemon=True,
                )
                t.start()
                self.threads.append(t)
            else:
                logger.warning("No command builder defined for tool '%s'", tool_name)

        self._supervise_thread("EventDispatcher", self.event_dispatcher.run)
        self._supervise_thread("AnomalyWatcher", self.anomaly_watcher.run)
        self._supervise_thread("LogCollector", self.log_collector_manager.run)
        self._supervise_thread("SpaceWatcher", self.space_watcher.run)
        self.stop_event.wait()
        self._shutdown()


def handle_signal(controller, signum, frame):
    """Handle termination signals to gracefully shut down the controller."""
    if __debug__:
        logger.info("Received signal %d, shutting down...", signum)
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
    # Simple logging setup - configure root logger
    # Performance optimized: Verbose logger.info calls wrapped in if __debug__
    # Use python -O for production to remove all debug overhead
    log_level = os.getenv('AOD_LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        main()
    except Exception as e:
        logging.error("Fatal error in main(): %s", e)
        if __debug__:
            logging.debug("Full traceback:", exc_info=True)