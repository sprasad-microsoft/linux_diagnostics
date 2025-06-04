import threading
import queue
import subprocess
import os
import signal
import time
import traceback
import yaml
import warnings
import signal
import platform
import re
import struct
import ctypes
import mmap
import numpy as np

from dataclasses import dataclass, field
from typing import Optional
from abc import ABC, abstractmethod
from enum import Enum

@dataclass(slots=True, frozen=True)
class AnomalyConfig:
    type: str
    tool: str
    acceptable_percentage: int
    default_threshold_ms: Optional[int] = None
    track: dict[str, Optional[int]] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)

@dataclass(slots=True, frozen=True)
class GuardianConfig:
    anomalies: dict[str, AnomalyConfig]

@dataclass(slots=True, frozen=True)
class WatcherConfig:
    actions: list[str]

@dataclass(slots=True, frozen=True)
class Config:  # top-level config
    watch_interval_sec: int
    aod_output_dir: str
    watcher: WatcherConfig
    guardian: GuardianConfig
    cleanup: dict  # could make a dataclass if desired
    audit: dict    # could make a dataclass if desired

from types import MappingProxyType
ALL_SMB_CMDS = MappingProxyType({
    "SMB2_NEGOTIATE": 0,
    "SMB2_SESSION_SETUP": 1,
    "SMB2_LOGOFF": 2,
    "SMB2_TREE_CONNECT": 3,
    "SMB2_TREE_DISCONNECT": 4,
    "SMB2_CREATE": 5,
    "SMB2_CLOSE": 6,
    "SMB2_FLUSH": 7,
    "SMB2_READ": 8,
    "SMB2_WRITE": 9,
    "SMB2_LOCK": 10,
    "SMB2_IOCTL": 11,
    "SMB2_CANCEL": 12,
    "SMB2_ECHO": 13,
    "SMB2_QUERY_DIRECTORY": 14,
    "SMB2_CHANGE_NOTIFY": 15,
    "SMB2_QUERY_INFO": 16,
    "SMB2_SET_INFO": 17,
    "SMB2_OPLOCK_BREAK": 18,
    "SMB2_SERVER_TO_CLIENT_NOTIFICATION": 19
})

import errno
error_codes = list(errno.errorcode.values())

class ConfigManager:
    def __init__(self, config_path: str):
        with open(config_path, 'r') as file:
            config_data = yaml.safe_load(file)

        # Parse watcher
        watcher = WatcherConfig(actions=config_data["watcher"]["actions"])

        # Parse guardian anomalies
        anomalies = {}
        for name, anomaly in config_data["guardian"]["anomalies"].items():
            
            # depending on the type of anomaly, i want to call different functions
            if anomaly["type"] == "Latency":
                track = self.get_latency_track_cmds(anomaly)
            elif anomaly["type"] == "Error":
                track = self.get_error_track_cmds(anomaly)

            anomalies[name] = AnomalyConfig(
                type=anomaly["type"],
                tool=anomaly["tool"],
                acceptable_percentage=anomaly["acceptable_percentage"],
                default_threshold_ms=anomaly.get("default_threshold_ms"),
                track=track,
                actions=anomaly.get("actions", [])
            )
        guardian = GuardianConfig(anomalies=anomalies)

        # Build the top-level config
        self.data = Config(
            watch_interval_sec=config_data["watch_interval_sec"],
            aod_output_dir=config_data["aod_output_dir"],
            watcher=watcher,
            guardian=guardian,
            cleanup=config_data["cleanup"],
            audit=config_data["audit"]
        )

    def validate_cmds(self, all_codes, track_codes, exclude_codes):
        
        #check if any track_codes are duplicated
        present_track_codes = set()
        for code in track_codes:
            if code not in all_codes:
                raise ValueError(f"Code {code} not found in error codes.")
            if code in present_track_codes:
                warnings.warn(f"Code {code} is duplicated in track codes.", UserWarning)
            present_track_codes.add(code)
        
        #check if any exclude_codes are duplicated
        present_exclude_codes = set()
        for code in exclude_codes:
            if code not in all_codes:
                raise ValueError(f"Code {code} not found in error codes.")
            if code in present_exclude_codes:
                warnings.warn(f"Code {code} is duplicated in exclude codes.", UserWarning)
            present_exclude_codes.add(code)
        
        #check if any track_codes are in exclude_codes
        for code in track_codes:
            if code in exclude_codes:
                raise ValueError(f"Code {code} is duplicated in track and exclude codes. It is unclear if Code {code} should be tracked or excluded.")

    def validate_smb_commands(self, track_commands, exclude_commands):

        # Handle missing TrackCommands (default to empty list)
        track_commands = track_commands if track_commands is not None else []
        exclude_commands = exclude_commands if exclude_commands is not None else []

        # Use an integer where 2^i indicates if i-th command is present
        present_track_cmds = 0
        present_exclude_cmds = 0

        #Checks for duplicate track commands
        for command in track_commands:
            if "command" not in command:
                raise ValueError(f"Missing 'command' key in TrackCommands: {command}")
            try:
                cmd = command["command"]
                if cmd in ALL_SMB_CMDS:
                    if present_track_cmds & (1 << ALL_SMB_CMDS[cmd]):
                        warnings.warn(f"Command {cmd} is duplicated in track commands.", UserWarning)
                        continue
                    if "threshold" in command and (not isinstance(command["threshold"], (int, float)) or command["threshold"] < 0):
                        raise ValueError(f"Invalid threshold value in track command: {command}")
                    present_track_cmds |= (1 << ALL_SMB_CMDS[cmd])
                else:
                    raise ValueError(f"Command {cmd} not found in ALL_SMB_CMDS.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid track command format: {command}")
            
        #Check for duplicate exclude commands
        for cmd in exclude_commands:
            try:
                if cmd in ALL_SMB_CMDS:
                    if present_exclude_cmds & (1 << ALL_SMB_CMDS[cmd]):
                        warnings.warn(f"Command {cmd} is duplicated in exclude commands.", UserWarning)
                        continue 
                    present_exclude_cmds |= (1 << ALL_SMB_CMDS[cmd])
                else:
                    raise ValueError(f"Command {cmd} not found in ALL_SMB_CMDS.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid exclude command format: {command}")

        # Check for duplicate commands between track and exclude
        for command in exclude_commands:
            try:
                cmd = command
                if cmd in ALL_SMB_CMDS:
                    if present_track_cmds & (1 << ALL_SMB_CMDS[cmd]):
                        raise ValueError(f"Command {cmd} is duplicated in track or exclude commands. It is unclear if Command {cmd} should be tracked or excluded.")
                else:
                    raise ValueError(f"Command {cmd} not found in ALL_SMB_CMDS.")
            except (TypeError, KeyError):
                raise ValueError(f"Invalid exclude command format: {command}")

    def get_track_codes(self, mode, all_codes, track_codes, exclude_codes):

        if mode == "trackonly":
            return {code: None for code in track_codes}
        else:
            exclude_set = set(exclude_codes)
            return {code: None for code in all_codes if code not in exclude_set}

    def get_latency_track_cmds(self, anomaly):
        track_commands = anomaly.get("track_commands", [])
        exclude_commands = anomaly.get("exclude_commands", [])
        latency_mode = anomaly.get("mode", "all")

        # Validate latency mode constraints
        if latency_mode == "trackonly" and exclude_commands:
            warnings.warn("Exclude commands will be ignored in trackonly mode.")
            exclude_commands = []
        elif latency_mode == "excludeonly" and track_commands:
            warnings.warn("Track commands will be ignored in excludeonly mode.")
            track_commands = []

        self.validate_smb_commands(track_commands, exclude_commands)

        # Initialize all commands to -1
        command_map = {cmd: -1 for cmd in ALL_SMB_CMDS}
        default_threshold = anomaly.get("default_threshold_ms", 10)

        # Apply thresholds based on mode
        if latency_mode == "trackonly":
            for cmd in track_commands:
                command = cmd["command"]
                threshold = cmd.get("threshold", default_threshold)
                command_map[command] = threshold
        elif latency_mode == "excludeonly":
            for cmd in command_map:
                command_map[cmd] = default_threshold
            for cmd in exclude_commands:
                if cmd in command_map:
                    del command_map[cmd]
            print("haha")
        else:  # mode == "all"
            for cmd in command_map:
                command_map[cmd] = default_threshold
            for cmd in track_commands:
                command = cmd["command"]
                threshold = cmd.get("threshold", default_threshold)
                command_map[command] = threshold
            for cmd in exclude_commands: #delete if it is over here
                if cmd in command_map:
                    del command_map[cmd]

        return command_map

    def get_error_track_cmds(self, anomaly):
        
        track_codes = anomaly.get("track_codes", [])
        exclude_codes = anomaly.get("exclude_codes", [])
        error_mode = anomaly.get("mode", "all")

        # Validate error mode constraints
        if error_mode == "trackonly" and exclude_codes:
            warnings.warn("Exclude codes will be ignored in trackonly mode.")
            exclude_codes = []
        elif error_mode == "excludeonly" and track_codes:
            warnings.warn("Track codes will be ignored in excludeonly mode.")
            track_codes = []

        # Validate track and exclude codes
        self.validate_cmds(error_codes, track_codes, exclude_codes)
        
        return self.get_track_codes(error_mode, error_codes, track_codes, exclude_codes)

SHM_NAME = "/bpf_shm"
TASK_COMM_LEN = 16

HEAD_TAIL_BYTES = 8 if platform.architecture()[0] == '64bit' else 4

# def get_define_value(header_path, macro):
#     with open(header_path) as f:
#         for line in f:
#             m = re.match(rf'#define\s+{macro}\s+(\d+)', line)
#             if m:
#                 return int(m.group(1))
#     raise ValueError(f"{macro} not found in {header_path}")

# SMBDIAG_HEADER = os.path.join(os.path.dirname(__file__), "smbdiag.h")
# MAX_ENTRIES = get_define_value(SMBDIAG_HEADER, "MAX_ENTRIES")
# PAGE_SIZE = get_define_value(SMBDIAG_HEADER, "PAGE_SIZE")
#above stuff will work after we get the ebpf script, for now, just write manually
MAX_ENTRIES = 2048  # Example value, replace with actual
PAGE_SIZE = 4096  # Example value, replace with actual

SHM_SIZE = ((MAX_ENTRIES + 1) * PAGE_SIZE)
SHM_DATA_SIZE = (SHM_SIZE//1000 - 2 * HEAD_TAIL_BYTES)  # delete /10 later
class Metrics(ctypes.Union):
    _fields_ = [
        ("latency_ns", ctypes.c_ulonglong),
        ("retval", ctypes.c_int)
    ]

class Event(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_int),
        ("cmd_end_time_ns", ctypes.c_ulonglong),
        ("session_id", ctypes.c_ulonglong),
        ("mid", ctypes.c_ulonglong),
        ("smbcommand", ctypes.c_ushort),
        ("metric", Metrics),
        ("tool", ctypes.c_ubyte),
        ("is_compounded", ctypes.c_ubyte),
        ("task", ctypes.c_char * TASK_COMM_LEN)
    ]

event_dtype = np.dtype([
    ('pid', np.int32),
    ('cmd_end_time_ns', np.uint64),
    ('session_id', np.uint64),
    ('mid', np.uint64),
    ('smbcommand', np.uint16),
    ('metric_latency_ns', np.uint64),
    ('tool', np.uint8),
    ('is_compounded', np.uint8),
    ('task', f'S{TASK_COMM_LEN}')
], align=True)

class EventDispatcher:
    def __init__(self, controller):
        self.controller = controller
        created = False
        shm_path = f"/dev/shm{SHM_NAME}"
        try:
            self.fd = os.open(shm_path, os.O_RDWR)
        except FileNotFoundError:
            # Try to create if not found
            self.fd = os.open(shm_path, os.O_RDWR | os.O_CREAT, 0o666)
            created = True
        except Exception as e:
            print(f"Failed to open shared memory: {e}")
            raise

        if created:
            try:
                os.ftruncate(self.fd, SHM_SIZE)
            except Exception as e:
                print(f"Failed to set size of shared memory: {e}")
                os.close(self.fd)
                raise

        try:
            self.m = mmap.mmap(self.fd, SHM_SIZE, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE)
        except Exception as e:
            print(f"Failed to map shared memory: {e}")
            os.close(self.fd)
            raise

    def run(self):
        print("EventDispatcher started running")
        while not self.controller.stop_event.is_set():
            raw_events = self._poll_shm_buffer()
            batch = self._parse(raw_events)
            if batch is not None and len(batch) > 0:
                self.controller.eventQueue.put(batch)
            time.sleep(1)  # Adjust as needed

    def _poll_shm_buffer(self) -> bytes:
        """Fetch a batch of raw events from shared memory."""
        self.m.seek(0)
        head = struct.unpack_from("<Q", self.m, 0)[0]
        tail = struct.unpack_from("<Q", self.m, 8)[0]
        print(f"[AOD] head={head}, tail={tail}")
        event_size = ctypes.sizeof(Event)
        events = []

        if tail == head:
            return b''

        if tail < head:
            available = head - tail
            count = available // event_size
            offset = tail % SHM_DATA_SIZE
            self.m.seek(2 * HEAD_TAIL_BYTES + offset)
            raw = self.m.read(count * event_size)
            tail = (tail + count * event_size) % SHM_DATA_SIZE
            self._update_tail(tail)
            return raw
        else:
            # Wrap-around case
            available = (SHM_DATA_SIZE - tail) + head
            offset = tail % SHM_DATA_SIZE
            bytes_to_end = SHM_DATA_SIZE - offset
            self.m.seek(2 * HEAD_TAIL_BYTES + offset)
            raw1 = self.m.read(bytes_to_end)
            self.m.seek(2 * HEAD_TAIL_BYTES)
            raw2 = self.m.read(head)
            tail = (tail + available) % SHM_DATA_SIZE
            self._update_tail(tail)
            return raw1 + raw2

    def _update_tail(self, tail):
        self.m.seek(8)
        self.m.write(struct.pack("<Q", tail))
        self.m.flush()

    def _parse(self, raw: bytes):
        """Convert raw struct bytes to a numpy array of events (batch)."""
        if not raw:
            return None
        return np.frombuffer(raw, dtype=event_dtype)

    def cleanup(self):
        try:
            # Read head and tail before closing mmap
            self.m.seek(0)
            head = struct.unpack_from("<Q", self.m, 0)[0]
            tail = struct.unpack_from("<Q", self.m, 8)[0]
            if head != tail:
                print("EventDispatcher: Warning - head and tail are not equal, indicating potential data loss.")

            self.m.close()
            os.close(self.fd)
            os.unlink(f"/dev/shm{SHM_NAME}")
            print("EventDispatcher: Shared memory cleaned up")
        except OSError as e:
            print(f"EventDispatcher: Error cleaning up shared memory: {e}")

class AnomalyType(Enum):
    LATENCY = "latency"
    ERROR = "error"
    # Add more types as needed

class AnomalyHandler(ABC):
    def __init__(self, config: AnomalyConfig):
        self.config = config

    @abstractmethod
    def detect(self, arr: np.ndarray) -> bool:
        """Return True if anomaly detected."""
        pass

class LatencyAnomalyHandler(AnomalyHandler):
    def detect(self, arr: np.ndarray) -> bool:
        threshold_lookup = np.full(max(ALL_SMB_CMDS.values()) + 1, -1, dtype=np.int64)
        for cmd, threshold in self.config.track.items():
            if cmd in ALL_SMB_CMDS and threshold is not None and threshold >= 0:
                threshold_lookup[ALL_SMB_CMDS[cmd]] = threshold * 1_000_000

        thresholds = threshold_lookup[arr["smbcommand"]]
        valid_mask = thresholds >= 0
        anomaly_mask = (arr["metric_latency_ns"] >= thresholds) & valid_mask
        count = np.sum(anomaly_mask)

        print(arr) #for debugging

        print(f"[AnomalyHandler] Detected {count} latency anomalies for {self.config.tool}")
        return count >= 9

class ErrorAnomalyHandler(AnomalyHandler):
    def detect(self, arr: np.ndarray) -> bool:
        # Placeholder for error detection logic
        return False  # Replace with actual logic

class AnomalyWatcher:
    def __init__(self, controller):
        self.controller = controller
        self.interval = self.controller.config.watch_interval_sec
        self.handlers: dict[AnomalyType, AnomalyHandler] = self._load_anomaly_handlers(controller.config)

    def _load_anomaly_handlers(self, config) -> dict:
        handlers = {}
        for name, anomaly_cfg in config.guardian.anomalies.items():
            if anomaly_cfg.type.lower() == "latency":
                handlers[AnomalyType.LATENCY] = LatencyAnomalyHandler(anomaly_cfg)
            elif anomaly_cfg.type.lower() == "error":
                handlers[AnomalyType.ERROR] = ErrorAnomalyHandler(anomaly_cfg)
        return handlers

    def _get_batch(self):
        """Get a batch of events from the eventQueue."""
        try:
            batch = self.controller.eventQueue.get(timeout=1)
            return batch
        except queue.Empty:
            return None

    def run(self) -> None:
        """Loop: poll eventQueue, detect anomalies, and put actions into anomalyActionQueue"""
        while not self.controller.stop_event.is_set():
            while True:
                try:
                    batch = self.controller.eventQueue.get_nowait()
                    #print each event (reomve this code later)
                    #for event in batch:
                        #print(f"Event: {event}")
                except queue.Empty:
                    break  # Queue is empty, exit inner loop
                for anomaly_type, handler in self.handlers.items():
                    # ...filtering and detection logic...
                    # this will only filter latency anomalies for now
                    filtered_batch = batch[batch["tool"] == 7]
                    if handler.detect(filtered_batch):
                        action = self._generate_action(anomaly_type, filtered_batch)
                        self.controller.anomalyActionQueue.put(action)
            time.sleep(self.interval)
    
    def _generate_action(self, anomaly_type: AnomalyType, batch: np.ndarray) -> dict:
        """Generate an action based on the detected anomaly."""
        timestamp = int(time.time() * 1e9)  # nanoseconds since epoch
        return {
            "anomaly": anomaly_type,
            "timestamp": timestamp,
        }

class LogCollectorManager:
    def __init__(self, controller):
        self.controller = controller

    def run(self):
        print("LogCollectorManager started running")
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
        print("LogCompressor started running")
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
        print("AuditLogger started running")
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
        print("SpaceWatcher started running")
        while not self.controller.stop_event.is_set():
            time.sleep(self.controller.config.cleanup["cleanup_interval_sec"])
            print("Performed space cleanup")

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
   
    def set_death_signal():
        # PR_SET_PDEATHSIG = 1
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl(1, signal.SIGKILL)

    def _start_ebpf_process(self):
        wrapper_path = os.path.join(os.path.dirname(__file__), "pdeathsig_wrapper.py")
        self.ebpf_process = subprocess.Popen(
            ["python3", wrapper_path, "/bin/sleep", "1000"],
            preexec_fn=os.setsid
        )
        print(f"Started new eBPF process with PID {self.ebpf_process.pid}")

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


    def run(self) -> None:

        process_thread = threading.Thread(target=self._supervise_process, name="ProcessSupervisor", daemon=True)
        process_thread.start()
        print(f"Started thread eBPFProcessSupervisor with ID {process_thread.ident}")
        self.threads.append(process_thread)
        
        self.event_dispatcher = EventDispatcher(self)
        self._supervise_thread("EventDispatcher", self.event_dispatcher.run)
        self._supervise_thread("AnomalyWatcher", AnomalyWatcher(self).run)
        self._supervise_thread("LogCollector", LogCollectorManager(self).run)
        self._supervise_thread("LogCompressor", LogCompressor(self).run)
        self._supervise_thread("AuditLogger", AuditLogger(self).run)
        self._supervise_thread("SpaceWatcher", SpaceWatcher(self).run)
        self.stop_event.wait()
        self._shutdown()

def handle_signal(signum, frame):
    print(f"Received signal {signum}, shutting down...")
    controller.stop()

if __name__ == "__main__":
    # Use the config path relative to this file, as in controller_draft.py
    config_path = os.path.join(os.path.dirname(__file__), "../config/config.yaml")
    controller = Controller(config_path)

    # should i specify this in the Controller constructor?
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    controller.run()