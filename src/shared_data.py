from dataclasses import dataclass, field
from typing import Optional
import ctypes
import numpy as np
from types import MappingProxyType
import errno

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

error_codes = list(errno.errorcode.values())

SHM_NAME = "/bpf_shm"
TASK_COMM_LEN = 16

#Assuming we are working with x64 architecture for now
HEAD_TAIL_BYTES = 8
MAX_ENTRIES = 2048  
PAGE_SIZE = 4096  

SHM_SIZE = ((MAX_ENTRIES + 1) * PAGE_SIZE)
SHM_DATA_SIZE = (SHM_SIZE//10 - 2 * HEAD_TAIL_BYTES)  # delete /10 later

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

#we need to ensure that event_dtype and event cstruct is of the same size
event_dtype = np.dtype([
    ('pid', np.int32),
    ('cmd_end_time_ns', np.uint64),
    ('session_id', np.uint64),
    ('mid', np.uint64),
    ('smbcommand', np.int16),
    ('metric_latency_ns', np.uint64),
    ('tool', np.uint8),
    ('is_compounded', np.uint8),
    ('task', f'S{TASK_COMM_LEN}')
], align=True)
