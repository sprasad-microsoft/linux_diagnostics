# API Reference Guide

This document provides comprehensive API documentation for all classes, methods, and functions in the AODv2 codebase. Use this as a reference when developing or extending the system.

## 📋 Table of Contents

1. [🎮 Core Classes](#-core-classes)
   - [Controller](#controller) - Main orchestrator with tool command builders registry
   - [EventDispatcher](#eventdispatcher) - Event processing and filtering
   - [AnomalyWatcher](#anomalywatcher) - Anomaly detection with handler registry
   - [LogCollector](#logcollector) - Diagnostic collection with action factory
   - [SpaceWatcher](#spacewatcher) - Disk space monitoring

2. [🔍 Utility Functions](#-utility-functions)
   - [config_schema](#config_schema) - Configuration data structures
   - [anomaly_type](#anomaly_type) - Anomaly type enums and mappings
   - [pdeathsig_wrapper](#pdeathsig_wrapper) - Process death signal handling
   - [set_thread_name](#set_thread_name) - Thread naming for system monitoring

3. [🌐 Global Variables and Constants](#-global-variables-and-constants)
   - [shared_data](#shared_data) - Shared memory and SMB command mappings
   - [AnomalyWatcher Registries](#anomalywatcher-registries) - Handler registry

4. [ Data Formats](#-data-formats)
   - [Event Format](#event-format) - eBPF event structure
   - [Anomaly Format](#anomaly-format) - Anomaly event structure

5. [🧪 Test Suite](#-test-suite)
   - [Core Component Tests](#core-component-tests)
   - [Handler Tests](#handler-tests)
   - [Utility Tests](#utility-tests)
   - [Integration Tests](#integration-tests)

---

## 🎮 Core Classes

### Controller
**File:** `src/Controller.py`

Main orchestrator class that manages all system components.

#### Constructor
```python
def __init__(self, config_path: str)
```
**Parameters:**
- `config_path` (str): Path to the YAML configuration file

**Description:** Initializes the Controller with configuration and sets up all system components.

#### Class Variables

##### `tool_cmd_builders`
```python
self.tool_cmd_builders = {
    "smbslower": self._get_smbsloweraod_cmd,
    # "smbiosnoop": self._get_smbiosnoop_cmd,
}
```
**Description:** Registry of eBPF tool command builders. Maps tool names to functions that generate command lines.

#### Instance Variables

##### `eventQueue`
```python
self.eventQueue: queue.Queue
```
**Description:** Thread-safe queue for events from EventDispatcher to AnomalyWatcher.

##### `anomalyActionQueue`
```python
self.anomalyActionQueue: queue.Queue
```
**Description:** Thread-safe queue for anomaly actions from AnomalyWatcher to LogCollector.

##### `tool_processes`
```python
self.tool_processes: dict
```
**Description:** Dictionary tracking running eBPF tool processes by name.

##### `stop_event`
```python
self.stop_event: threading.Event
```
**Description:** Event used to signal all threads and processes to stop.

#### Methods

##### `run()`
```python
def run() -> None
```
**Description:** Start all supervisor threads and wait for shutdown.

**Processing Flow:**
1. Extract tools from configuration
2. Start tools as processes and supervisor threads for each tool
3. Start component threads (EventDispatcher, AnomalyWatcher, LogCollector, SpaceWatcher)
4. Wait for shutdown signal

##### `stop()`
```python
def stop() -> None
```
**Description:** Signal all threads and processes to stop by setting the stop event.

##### `_shutdown()`
```python
def _shutdown() -> None
```
**Description:** Performs graceful shutdown of all components.

**Shutdown Sequence:**
1. Sends sentinel values (None) to queues to signal component shutdown
2. Wait for all queues to be processed (with join())
3. Wait for threads to complete processing (with timeout)
4. Clean up EventDispatcher resources

**Sentinel Handling:**
- Places `None` sentinel in `anomalyActionQueue` to stop LogCollector
- EventDispatcher stops naturally when `stop_event` is set (no sentinel needed)
- AnomalyWatcher stops when it processes the `None` sentinel from eventQueue and `stop_event` is set
- LogCollector stops when it receives the `None` sentinel from anomalyActionQueue
- Components recognize sentinel values and perform graceful shutdown

##### `_supervise_thread(thread_name: str, target: callable, *args, **kwargs)`
```python
def _supervise_thread(self, thread_name: str, target: callable, *args, **kwargs) -> None
```
**Description:** Start and supervise a thread, restarting it if it dies unexpectedly.

##### `_supervise_process(process_name: str, cmd_builder: callable)`
```python
def _supervise_process(self, process_name: str, cmd_builder: callable) -> None
```
**Description:** Supervise a process, restarting it if it exits unexpectedly.

#### Module Functions

##### `handle_signal(controller, signum, frame)`
```python
def handle_signal(controller, signum, frame) -> None
```
**Parameters:**
- `controller` (Controller): Controller instance to stop
- `signum` (int): Signal number received
- `frame`: Stack frame (unused)

**Description:** Signal handler for graceful shutdown. Handles SIGTERM and SIGINT (Ctrl+C) signals to initiate clean shutdown of the Controller and all its components.

**Registered Signals:**
- `SIGTERM` - Termination signal (e.g., from `kill` command)
- `SIGINT` - Interrupt signal (Ctrl+C)

**Behavior:**
1. Logs the received signal number
2. Calls `controller.stop()` to initiate graceful shutdown
3. Allows all components to finish processing and clean up resources

##### `main()`
```python
def main() -> None
```
**Description:** Main entry point for the AODv2 controller daemon. Sets up signal handlers and starts the controller.

**Functionality:**
1. **Root Check:** Verifies the script is running as root (required for eBPF programs)
2. **Configuration:** Loads config from `../config/config.yaml` relative to the script location
3. **Signal Setup:** Registers signal handlers for graceful shutdown
4. **Controller Start:** Creates and runs the Controller instance

**Raises:** RuntimeError if not running as root

**Usage:** Called when `src/Controller.py` is executed directly

---

### EventDispatcher
**File:** `src/EventDispatcher.py`

Handles collection and processing of events from eBPF programs.

#### Constructor
```python
def __init__(self, controller)
```
**Parameters:**
- `controller`: Reference to the Controller instance

#### Methods

##### `run()`
```python
def run() -> None
```
**Description:** Main event collection loop. Polls shared memory ring buffer and processes events.

**Processing Flow:**
1. Poll shared memory buffer for new events
2. Waits for atleast 10 events or 3 seconds
3. **Timing Control:** Uses `MAX_WAIT` (5ms) sleep before reading to allow some events to accumulate
4. Parse raw bytes into numpy arrays
5. Queue events as a batch to `eventQueue` for analysis by AnomalyWatcher

**Event Processing:**
- Batches events for efficient processing
- Uses `MAX_WAIT` constant for timing coordination with eBPF programs
- Continues until stop event is signaled

##### `_setup_shared_memory()`
```python
def _setup_shared_memory() -> tuple[int, mmap.mmap]
```
**Description:** Open, create, size, and memory-map the shared memory segment.

**Returns:** Tuple of file descriptor and mmap object

##### `_poll_shm_buffer()`
```python
def _poll_shm_buffer() -> bytes
```
**Description:** Poll the shared memory buffer for new events.

**Returns:** Raw bytes from the ring buffer

##### `_parse(raw: bytes)`
```python
def _parse(self, raw: bytes) -> np.ndarray | None
```
**Description:** Parse raw bytes into numpy array of events.

**Returns:** Numpy array of parsed events or None if no events

##### `cleanup()`
```python
def cleanup() -> None
```
**Description:** Clean up shared memory resources.

---

### AnomalyWatcher
**File:** `src/AnomalyWatcher.py`

Analyzes events in batches to detect anomalies using configurable handlers.

#### Constructor
```python
def __init__(self, controller)
```
**Parameters:**
- `controller`: Reference to the Controller instance

**Initialization:**
- Loads anomaly handlers from `ANOMALY_HANDLER_REGISTRY`
- Sets up metrics tracking (if debug mode)
- Configures watch interval from config

#### Class Variables

##### `ANOMALY_HANDLER_REGISTRY`
```python
ANOMALY_HANDLER_REGISTRY = {
    AnomalyType.LATENCY: LatencyAnomalyHandler,
    AnomalyType.ERROR: ErrorAnomalyHandler,
    # Add more types here as needed
}
```
**Description:** Global registry mapping anomaly types to their handler classes.

**Usage:** Used by `_load_anomaly_handlers()` to instantiate the correct handler for each configured anomaly type.

#### Instance Variables

##### `handlers`
```python
self.handlers: dict[AnomalyType, AnomalyHandler]
```
**Description:** Dictionary of loaded anomaly handler instances, populated during initialization based on configuration.

##### `interval`
```python
self.interval: int
```
**Description:** Watch interval in seconds (from config `watch_interval_sec`, defaults to 1).

#### Methods

##### `run()`
```python
def run() -> None
```
**Description:** Main analysis loop with configurable batch processing intervals.

**Processing Flow:**
1. Waits for the `event queue` to become non empty
2. Drain `event queue` for `MAX_WAIT` seconds (to let more batches accumulate)
3. Process events through registered handlers
4. Queue detected anomalies to `anomalyActionQueue`
5. Calls `eventQueue.task_done()`
6. Sleep for `watch_interval_sec`

**Event Processing:**
- Processes event batches from EventDispatcher
- Sends anomaly actions to LogCollector
- Handles graceful shutdown when stop event is set

##### `_load_anomaly_handlers(config)`
```python
def _load_anomaly_handlers(self, config) -> dict[AnomalyType, AnomalyHandler]
```
**Description:** Load and configure anomaly handlers based on configuration.

**Returns:** Dictionary mapping anomaly types to handler instances

##### `_generate_action(anomaly_type: AnomalyType)`
```python
def _generate_action(self, anomaly_type: AnomalyType) -> dict
```
**Description:** Generate action dictionary for detected anomaly.

**Returns:** Dictionary containing anomaly type and time stamp


---

### LogCollector
**File:** `src/LogCollector.py`

Executes diagnostic collection using async QuickActions when anomalies are detected.

#### Constructor
```python
def __init__(self, controller)
```
**Parameters:**
- `controller`: Reference to the Controller instance

#### Instance Variables

##### `action_factory`
```python
self.action_factory = {
    "journalctl": lambda: JournalctlQuickAction(self.aod_output_dir, self.anomaly_interval),
    "stats": lambda: CifsstatsQuickAction(self.aod_output_dir),
    "debugdata": lambda: DebugDataQuickAction(self.aod_output_dir),
    "dmesg": lambda: DmesgQuickAction(self.aod_output_dir, self.anomaly_interval),
    "mounts": lambda: MountsQuickAction(self.aod_output_dir),
    "smbinfo": lambda: SmbinfoQuickAction(self.aod_output_dir),
    "syslogs": lambda: SysLogsQuickAction(self.aod_output_dir, num_lines=100),
}
```
**Description:** Factory registry that maps action names to QuickAction instance creators. Used to instantiate diagnostic collection handlers based on configuration.

##### `handlers`
```python
self.handlers: dict[AnomalyType, list[QuickAction]]
```
**Description:** Mapping from anomaly types to lists of QuickAction instances. Built from configuration and action_factory during initialization.

##### `loop`
```python
self.loop: asyncio.AbstractEventLoop
```
**Description:** Dedicated event loop for async log collection operations.

##### `max_concurrent_tasks`
```python
self.max_concurrent_tasks: int = 4
```
**Description:** Maximum number of concurrent log collection tasks.

##### `anomaly_interval`
```python
self.anomaly_interval: int
```
**Description:** Time interval for anomaly detection, used by some QuickActions.

##### `aod_output_dir`
```python
self.aod_output_dir: str
```
**Description:** Output directory for collected diagnostic logs.

##### Debug Metrics Variables
```python
self.tasks_processed: int  # Available only in debug mode
self.tasks_failed: int     # Available only in debug mode
```
**Description:** Counters for tracking task success/failure rates (debug builds only).

#### Methods

##### `run()`
```python
def run() -> None
```
**Description:** Main event loop for processing anomaly events (wrapper that starts async event loop).

**Implementation:**
- Sets up dedicated event loop for async operations
- Runs until completion using `loop.run_until_complete(self._run())`
- Closes event loop on completion

##### `_run()`
```python
async def _run() -> None
```
**Description:** Main async event loop for processing anomaly events.

**Processing Flow:**
1. Creates semaphore for concurrent task limiting (`max_concurrent_tasks`)
2. Continuously polls `controller.anomalyActionQueue` for new anomaly events
3. Creates async tasks for each anomaly event with concurrency control
4. Handles sentinel value (None) to gracefully stop the loop
5. Waits for all running tasks to complete before exiting

**Features:**
- Concurrent anomaly processing with semaphore-based limits
- Task tracking with `currently_running_tasks` set
- Graceful shutdown handling
- Exception handling for individual events

##### `get_anomaly_events(config)`
```python
def get_anomaly_events(self, config) -> dict
```
**Description:** Builds mapping from anomaly types to action instances based on configuration.

**Processing Logic:**
1. Iterates through `config.guardian.anomalies`
2. For each anomaly, extracts `actions` list from configuration
3. Uses `action_factory` to create QuickAction instances for each action name
4. Maps anomaly type enum to list of action instances
5. Logs warnings for unknown action names or anomaly types

**Returns:** Dictionary mapping `AnomalyType` enum values to lists of QuickAction instances

##### `_create_log_collection_task(anomaly_event)`
```python
async def _create_log_collection_task(self, anomaly_event) -> None
```
**Description:** Executes log collection for a single anomaly event.

**Processing Steps:**
1. Extracts anomaly type and timestamp from event
2. Executes all configured QuickActions concurrently using `asyncio.gather()`
3. Compresses collected logs using tar + zstd compression
4. Cleans up temporary directories after compression

**Compression:**
- Uses zstd compression (level 3) for optimal speed/compression balance
- Creates tar.zst archive with all collected diagnostic data
- Removes original uncompressed directory after archiving

##### `_create_log_collection_task_with_limit(anomaly_event, semaphore)`
```python
async def _create_log_collection_task_with_limit(self, anomaly_event, semaphore: asyncio.Semaphore) -> None
```
**Description:** Wrapper for log collection task with concurrency control and metrics.

**Features:**
- **Semaphore Control:** Uses async semaphore to limit concurrent tasks
- **Metrics Tracking:** Updates `tasks_processed` and `tasks_failed` counters (debug mode)
- **Error Handling:** Catches and logs exceptions without stopping other tasks
- **Queue Management:** Signals task completion to `anomalyActionQueue` using `task_done()`
- **Performance Monitoring:** Logs success rate metrics every 10 tasks (debug mode)

**Task Completion Protocol:**
- Always calls `anomalyActionQueue.task_done()` regardless of success/failure
- Ensures proper queue synchronization for graceful shutdown
- Maintains accurate task completion tracking for queue join operations


---

### SpaceWatcher
**File:** `src/SpaceWatcher.py`

Manages disk usage by monitoring and cleaning up log storage. Uses dual cleanup strategy (size and age-based) and only processes completed `.tar.zst` files to prevent race conditions with LogCollector.

#### Constructor
```python
def __init__(self, controller)
```
**Parameters:**
- `controller`: Reference to the Controller instance

**Configuration (from `controller.config.cleanup`):**
- `max_log_age_days` (default: 2) - Maximum age for log files
- `max_total_log_size_mb` (default: 200) - Maximum total size in MB
- `cleanup_interval_sec` (default: 60) - Cleanup check interval
- `aod_output_dir` (default: "/var/log/aod") - Base output directory

#### Instance Variables

##### Configuration Variables
```python
self.max_log_age_days: int = 2
self.max_total_log_size_mb: int = 200  
self.cleanup_interval: int = 60
self.aod_output_dir: str = "/var/log/aod"
self.batches_dir: Path  # Points to aod_output_dir/batches
self.last_full_cleanup: float  # Timestamp of last full cleanup
```

#### Global Constants

##### `SIZE_DELETE_THRESHOLD`
```python
SIZE_DELETE_THRESHOLD = 0.5
```
**Description:** Cleanup stops when total size reaches 50% of maximum allowed size.

#### Methods

##### `run()`
```python
def run() -> None
```
**Description:** Main cleanup loop with dual strategy: size-based (triggered at 90% capacity) and age-based (periodic based on max_log_age_days).

##### `_check_space()`
```python
def _check_space() -> bool
```
**Description:** Monitors disk usage by scanning `.tar.zst` files and returns True if cleanup needed (>90% threshold).

##### `_full_cleanup_needed()`
```python
def _full_cleanup_needed() -> bool
```
**Description:** Determines if periodic age-based cleanup should run based on last cleanup timestamp.

##### `cleanup_by_age()`
```python
def cleanup_by_age() -> None
```
**Description:** Removes entries older than `max_log_age_days` using numpy arrays for efficient timestamp filtering.

##### `cleanup_by_size()`
```python
def cleanup_by_size() -> None
```
**Description:** Removes oldest entries until total size ≤ `max_total_log_size_mb` SIZE_DELETE_THRESHOLD`. Uses numpy for efficient sorting by modification time.

---

## 🎯 Base Classes

### AnomalyHandlerBase
**File:** `src/base/AnomalyHandlerBase.py`

Abstract base class for anomaly detection handlers.

#### Constructor
```python
def __init__(self, config)
```
**Parameters:**
- `config`: Configuration object for the handler

#### Abstract Methods

##### `detect(events_batch: np.ndarray)`
```python
def detect(events_batch: np.ndarray) -> bool
```
**Parameters:**
- `events_batch` (np.ndarray): Batch of events to analyze

**Returns:** True if anomaly detected, False otherwise

**Must Implement:** Subclasses must implement anomaly detection logic.

---

### QuickAction
**File:** `src/base/QuickAction.py`

Abstract base class for diagnostic collection actions.

#### Constructor
```python
def __init__(self, batches_root: str, log_filename: str)
```
**Parameters:**
- `batches_root` (str): Root directory for batch output
- `log_filename` (str): Name of the log file to create

#### Instance Variables
```python
self.batches_root: str       # Root directory for batch outputs
self.log_filename: str       # Filename for the collected logs
```

#### Abstract Methods

##### `get_command()`
```python
def get_command() -> tuple[list[str], str]
```
**Returns:** Tuple of (command_list, command_type)
- For cat commands: (["cat", "/path/to/file"], "cat")
- For shell commands: (["command", "args"], "cmd")

**Must Implement:** Subclasses must implement command generation logic.

#### Provided Methods

##### `get_output_path(batch_id: str)`
```python
def get_output_path(batch_id: str) -> str
```
**Returns:** Full path to output file for this batch

##### `get_output_dir(batch_id: str)`
```python
def get_output_dir(batch_id: str) -> str
```
**Returns:** Directory path for this batch's outputs

##### `execute(batch_id: str)`
```python
async def execute(batch_id: str) -> None
```
**Description:** Main execution method that runs the command and collects output. Calls `get_command()` to determine the command type and delegates to appropriate helper method.

**Processing Flow:**
1. Gets output path for the batch
2. Calls `get_command()` to get command and type
3. If command type is "cat": calls `collect_cat_output()` with the file path
4. If command type is "cmd": calls `collect_cmd_output()` with the command list
5. Doesnt raise exception on failure and continues others actions

##### `collect_cat_output(in_path: str, out_path: str)`
```python
async def collect_cat_output(in_path: str, out_path: str) -> None
```
**Description:** Used for "cat" command types. Reads data directly from filesystem paths (like /proc files) and writes to output file.

**Used by:** QuickActions that return command type "cat" from `get_command()`

**Implementation:**
- Creates output directory if needed
- Reads bytes directly from input path using `Path.read_bytes()`
- Writes data to output path using `Path.write_bytes()`

##### `collect_cmd_output(cmd: list, out_path: str)`
```python
async def collect_cmd_output(cmd: list, out_path: str) -> None
```
**Description:** Used for "cmd" command types. Executes shell commands asynchronously and captures their stdout output.

**Used by:** QuickActions that return command type "cmd" from `get_command()`

**Implementation:**
- Creates subprocess using `asyncio.create_subprocess_exec()`
- Captures stdout (stderr is discarded)
- Writes command output to file if stdout is not empty

---

## 🎬 QuickAction Implementations

### DmesgQuickAction
**File:** `src/handlers/DmesgQuickAction.py`

Collects kernel messages using journalctl -k command.

#### Constructor
```python
def __init__(self, batches_root: str, anomaly_interval: int = 1)
```
**Parameters:**
- `batches_root` (str): Root directory for log batches
- `anomaly_interval` (int): Time interval in seconds to filter logs (default: 1)

#### Methods

##### `get_command()`
```python
def get_command() -> tuple[list[str], str]
```
**Returns:** `(["journalctl", "-k", "--since", f"{anomaly_interval} seconds ago"], "cmd")`

**Command:** `journalctl -k` - Gets kernel messages from systemd journal

**Output File:** `dmesg.log`

---

### JournalctlQuickAction
**File:** `src/handlers/JournalctlQuickAction.py`

Collects systemd journal entries for specified time range.

#### Constructor
```python
def __init__(self, batches_root: str, anomaly_interval: int = 1)
```
**Parameters:**
- `batches_root` (str): Root directory for log batches
- `anomaly_interval` (int): Time interval in seconds to filter logs (default: 1)

#### Methods

##### `get_command()`
```python
def get_command() -> tuple[list[str], str]
```
**Returns:** `(["journalctl", "--since", f"{anomaly_interval} seconds ago"], "cmd")`

**Command:** `journalctl --since` - Gets all systemd journal entries from specified time

**Output File:** `journalctl.log`

---

### DebugDataQuickAction
**File:** `src/handlers/DebugDataQuickAction.py`

Collects SMB debug information from kernel debug interfaces.

#### Constructor
```python
def __init__(self, batches_root: str)
```
**Parameters:**
- `batches_root` (str): Root directory for log batches

#### Methods

##### `get_command()`
```python
def get_command() -> tuple[list[str], str]
```
**Returns:** `(["cat", "/proc/fs/cifs/DebugData"], "cat")`

**Command:** `cat /proc/fs/cifs/DebugData` - Reads CIFS debug data from proc filesystem

**Output File:** `debug_data.log`

---

### CifsstatsQuickAction
**File:** `src/handlers/CifsstatsQuickAction.py`

Collects CIFS statistics and connection information.

#### Constructor
```python
def __init__(self, batches_root: str)
```
**Parameters:**
- `batches_root` (str): Root directory for log batches

#### Methods

##### `get_command()`
```python
def get_command() -> tuple[list[str], str]
```
**Returns:** `(["cat", "/proc/fs/cifs/Stats"], "cat")`

**Command:** `cat /proc/fs/cifs/Stats` - Reads CIFS statistics from proc filesystem

**Output File:** `cifsstats.log`

---

### MountsQuickAction
**File:** `src/handlers/MountsQuickAction.py`

Collects current filesystem mount information.

#### Constructor
```python
def __init__(self, batches_root: str)
```
**Parameters:**
- `batches_root` (str): Root directory for log batches

#### Methods

##### `get_command()`
```python
def get_command() -> tuple[list[str], str]
```
**Returns:** `(["cat", "/proc/mounts"], "cat")`

**Command:** `cat /proc/mounts` - Reads current filesystem mounts from proc filesystem

**Output File:** `mounts.log`

---

### SmbinfoQuickAction
**File:** `src/handlers/SmbinfoQuickAction.py`

Collects SMB file information using smbinfo tool.

#### Constructor
```python
def __init__(self, batches_root: str)
```
**Parameters:**
- `batches_root` (str): Root directory for log batches

#### Methods

##### `get_command()`
```python
def get_command() -> tuple[list[str], str]
```
**Returns:** `(["smbinfo", "-h", "filebasicinfo"], "cmd")`

**Command:** `smbinfo -h filebasicinfo` - Gets SMB file basic information using smbinfo utility

**Output File:** `smbinfo.log`

---

### SysLogsQuickAction
**File:** `src/handlers/SysLogsQuickAction.py`

Collects system log entries from /var/log/syslog.

#### Constructor
```python
def __init__(self, batches_root: str, num_lines: int = 100)
```
**Parameters:**
- `batches_root` (str): Root directory for log batches
- `num_lines` (int): Number of lines to fetch from syslog (default: 100)

#### Methods

##### `get_command()`
```python
def get_command() -> tuple[list[str], str]
```
**Returns:** `(["tail", f"-n{num_lines}", "/var/log/syslog"], "cmd")`

**Command:** `tail -n{num_lines} /var/log/syslog` - Gets last N lines from system log file

**Output File:** `syslogs.log`

---

## 🛠️ Anomaly Handler Implementations

### LatencyAnomalyHandler
**File:** `src/handlers/latency_anomaly_handler.py`

Detects latency anomalies using configurable per-command thresholds and numpy vectorization for efficient processing.

#### Constructor
```python
def __init__(self, latency_config)
```
**Parameters:**
- `latency_config`: Configuration object containing thresholds and acceptable count

**Initialization:**
- Sets up `acceptable_count` from config
- Creates `threshold_lookup` numpy array mapping SMB command IDs to thresholds (in nanoseconds)
- Converts millisecond thresholds to nanoseconds for direct comparison

#### Instance Variables

##### `acceptable_count`
```python
self.acceptable_count: int
```
**Description:** Maximum number of threshold violations allowed before triggering anomaly detection.

##### `threshold_lookup`
```python
self.threshold_lookup: np.ndarray
```
**Description:** Numpy array indexed by SMB command ID, containing threshold values in nanoseconds. Initialized with zeros and populated from config.track dictionary.

#### Methods

##### `detect(events_batch: np.ndarray)`
```python
def detect(events_batch: np.ndarray) -> bool
```
**Parameters:**
- `events_batch` (np.ndarray): Batch of events with fields `metric_latency_ns` and `smbcommand`

**Returns:** True if anomaly detected, False otherwise

**Detection Logic:**
1. **Threshold Lookup:** For each event, uses the SMB command ID to index into `threshold_lookup` array and get the corresponding threshold
2. **Vectorized Comparison:** Compares each event's latency against its command-specific threshold using `>=` operator across the entire batch
3. **Count Violations:** Uses `np.sum()` to count how many events exceed their thresholds (True values = 1, False = 0)
4. **Maximum Latency Check:** Uses `np.max()` to find the highest latency value in the batch
5. **Dual Trigger Conditions:**
   - Returns True if `anomaly_count >= acceptable_count`
   - Returns True if any single event exceeds 1 second (1e9 nanoseconds)

**Performance Features:**
- Uses numpy vectorization for efficient batch processing
- Direct array indexing for O(1) threshold lookup

---

## 🔧 Configuration Management

### Configuration Schema Utilities
**File:** `src/utils/config_schema.py`

Defines the data structures and schema for the AOD system configuration. These dataclasses provide type safety and structure for the YAML configuration that ConfigManager loads and validates.

#### Config
Top-level configuration dataclass containing all system settings.

##### Properties
```python
watch_interval_sec: int         # Anomaly detection interval in seconds
aod_output_dir: str            # Base output directory for logs
watcher: WatcherConfig         # Watcher configuration
guardian: GuardianConfig       # Guardian/anomaly configuration  
cleanup: dict                 # Cleanup settings
audit: dict                   # Audit settings
```

#### WatcherConfig
Configuration for watcher actions.

##### Properties
```python
actions: list[str]             # List of available QuickAction names
```

#### GuardianConfig
Configuration container for all anomaly detection rules.

##### Properties
```python
anomalies: dict[str, AnomalyConfig]  # Mapping of anomaly names to configurations
```

#### AnomalyConfig
Configuration for individual anomaly detection rules.

##### Properties
```python
type: str                      # Anomaly type ("latency" or "error")
tool: str                      # eBPF tool name
acceptable_count: int          # Threshold for triggering anomaly
default_threshold_ms: Optional[int]  # Default threshold in milliseconds
track: dict[int, Optional[int]]      # Mapping of IDs to thresholds (built by ConfigManager)
actions: list[str]            # QuickActions to execute on detection
```

---

### ConfigManager
**File:** `src/ConfigManager.py`

Loads and parses YAML configuration files, validates settings, and constructs the configuration data structures above.

#### Constructor
```python
def __init__(self, config_path: str)
```
**Parameters:**
- `config_path` (str): Path to the YAML configuration file

**Initialization:**
- Loads YAML configuration file
- Parses watcher and guardian sections
- Validates anomaly and tracking settings
- Builds final Config object stored in `self.data`

#### Instance Variables

##### `data`
```python
self.data: Config
```
**Description:** The parsed and validated configuration object containing all system settings.

#### Methods

##### `_load_yaml(config_path: str)`
```python
def _load_yaml(config_path: str) -> dict
```
**Description:** Loads and parses YAML configuration file with comprehensive error handling.

**Error Handling:**
- **FileNotFoundError:** Raises RuntimeError if config file doesn't exist
- **yaml.YAMLError:** Raises RuntimeError for invalid YAML syntax
- **Encoding:** Uses UTF-8 encoding for file reading

##### `_parse_watcher(config_data: dict)`
```python
def _parse_watcher(config_data: dict) -> WatcherConfig
```
**Description:** Parses the watcher section containing available QuickActions.

**Processing:**
1. **Extract Actions:** Gets the `actions` list from `config_data["watcher"]["actions"]`
2. **Create WatcherConfig:** Constructs WatcherConfig dataclass with the actions list
3. **Return:** Returns validated WatcherConfig object

**Example Config Section:**
```yaml
watcher:
  actions:
    - journalctl
    - stats
    - debugdata
    - dmesg
    - mounts
    - smbinfo
    - syslogs
```

##### `_parse_guardian(config_data: dict)`
```python
def _parse_guardian(config_data: dict) -> GuardianConfig
```
**Description:** Parses guardian section and validates all anomaly configurations with comprehensive validation.

**Processing Flow:**
1. **Extract Anomalies:** Gets anomaly definitions from `config_data["guardian"]["anomalies"]`
2. **Process Each Anomaly:**
   - Calls `_get_track_for_anomaly()` to build tracking configuration
   - Validates that tracking configuration is not empty
   - Creates `AnomalyConfig` dataclass with validated settings
3. **Build GuardianConfig:** Constructs final GuardianConfig with all anomaly configurations
4. **Return:** Returns validated GuardianConfig object

**Example Config Section:**
```yaml
guardian:
  anomalies:
    latency_anomaly:
      type: latency
      tool: smbslower
      acceptable_count: 5
      default_threshold_ms: 10
      mode: all
      track_commands:
        - command: SMB2_READ
          threshold: 50
        - command: SMB2_WRITE
          threshold: 100
      exclude_commands:
        - SMB2_NEGOTIATE
      actions:
        - journalctl
        - stats
```

##### `_build_config(config_data: dict, watcher: WatcherConfig, guardian: GuardianConfig)`
```python
def _build_config(config_data: dict, watcher: WatcherConfig, guardian: GuardianConfig) -> Config
```
**Description:** Builds the top-level Config object from parsed components.

**Parameters:**
- `config_data` (dict): Raw configuration data from YAML
- `watcher` (WatcherConfig): Parsed watcher configuration
- `guardian` (GuardianConfig): Parsed guardian configuration

**Returns:** Complete Config object with all system settings

##### `_get_track_for_anomaly(anomaly: dict)`
```python
def _get_track_for_anomaly(anomaly: dict) -> dict
```
**Description:** Dispatches to appropriate tracking function based on anomaly type using AnomalyType enum.

**Processing:**
1. **Type Parsing:** Extracts and validates anomaly type from config
2. **Enum Validation:** Converts string to AnomalyType enum with error handling
3. **Dispatch:** Routes to appropriate handler based on anomaly type:
   - `AnomalyType.LATENCY` → `_get_latency_track_cmds()`
   - `AnomalyType.ERROR` → `_get_error_track_cmds()`

**Error Handling:**
- **ValueError:** Raised for unknown anomaly types
- **ValueError:** Raised if no handler exists for the anomaly type

##### `_get_latency_track_cmds(anomaly: dict)`
```python
def _get_latency_track_cmds(anomaly: dict) -> dict
```
**Description:** Builds command-to-threshold mapping for latency anomaly detection with mode-based filtering.

**Processing:**
1. **Extract Configuration:** Gets track_commands, exclude_commands, mode, and default_threshold
2. **Normalize Lists:** Calls `_normalize_track_and_exclude()` to handle mode constraints
3. **Validate Commands:** Calls `_validate_smb_commands()` to check command validity
4. **Build Mapping:** Calls `_build_latency_command_map()` to create final command map

**Modes:**
- **"all"** (default): Track all commands with optional overrides and exclusions
- **"trackonly"**: Track only specified commands
- **"excludeonly"**: Track all except excluded commands

**Returns:** Dictionary mapping SMB command IDs to threshold values (in milliseconds)

##### `_get_error_track_cmds(anomaly: dict)`
```python
def _get_error_track_cmds(anomaly: dict) -> dict
```
**Description:** Builds error code tracking mapping for error anomaly detection.

**Processing:**
1. **Extract Configuration:** Gets track_codes, exclude_codes, and mode
2. **Normalize Lists:** Calls `_normalize_track_and_exclude()` to handle mode constraints
3. **Validate Codes:** Calls `_validate_cmds()` to check error code validity
4. **Build Mapping:** Calls `_get_track_codes()` to create final error code map

**Returns:** Dictionary mapping error code indices to None (indicating tracking enabled)

##### `_validate_smb_commands(track_commands: list, exclude_commands: list)`
```python
def _validate_smb_commands(track_commands: list, exclude_commands: list) -> None
```
**Description:** Validates SMB command names and threshold values for duplicates and correctness.

**Validation Steps:**
1. **Extract Command Names:** Extracts command names from track_commands dictionaries
2. **Command Validation:** Calls `_validate_cmds()` to check for duplicates and presence in ALL_SMB_CMDS
3. **Threshold Validation:** Calls `_validate_smb_thresholds()` to check threshold validity

##### `_validate_cmds(all_codes: list, track_codes: list, exclude_codes: list)`
```python
def _validate_cmds(all_codes: list, track_codes: list, exclude_codes: list) -> None
```
**Description:** Validates that track and exclude codes are present, not duplicated, and not overlapping.

**Validation Rules:**
- **Presence:** All codes must exist in all_codes
- **Uniqueness:** No duplicates within track_codes or exclude_codes
- **Non-overlapping:** No code can be in both track_codes and exclude_codes

##### `_validate_smb_thresholds(track_commands: list)`
```python
def _validate_smb_thresholds(track_commands: list) -> None
```
**Description:** Validates that all thresholds in track_commands are valid numeric values >= 0.

**Validation Rules:**
- **Type:** Must be int or float
- **Value:** Must be >= 0
- **Error:** Raises ValueError for invalid thresholds

##### `_check_codes(codes: list, all_codes: list, code_type: str)`
```python
def _check_codes(codes: list, all_codes: list, code_type: str) -> None
```
**Description:** Validates that codes are present in all_codes and not duplicated.

**Validation:**
- **Presence:** Each code must exist in all_codes
- **Uniqueness:** Warns about duplicates but allows them

##### `_normalize_track_and_exclude(mode: str, track_items: list, exclude_items: list, anomaly_type: str)`
```python
def _normalize_track_and_exclude(mode: str, track_items: list, exclude_items: list, anomaly_type: str) -> tuple
```
**Description:** Normalizes track and exclude items based on mode, warning about ignored items.

**Mode Handling:**
- **"trackonly":** Clears exclude_items and warns if they were provided
- **"excludeonly":** Clears track_items and warns if they were provided
- **"all":** Keeps both lists as-is

**Returns:** Tuple of (normalized_track_items, normalized_exclude_items)

##### `_build_latency_command_map(mode: str, track_commands: list, exclude_commands: list, default_threshold: int)`
```python
def _build_latency_command_map(mode: str, track_commands: list, exclude_commands: list, default_threshold: int) -> dict
```
**Description:** Builds the final command-to-threshold mapping for latency anomaly detection.

**Processing Logic:**
- **"trackonly":** Only includes specified commands with their thresholds
- **"excludeonly":** Includes all commands except excluded ones, using default_threshold
- **"all":** Includes all commands with default_threshold, applies overrides, removes excluded

**Returns:** Dictionary mapping SMB command IDs to threshold values

##### `_get_track_codes(mode: str, all_codes: list, track_codes: list, exclude_codes: list)`
```python
def _get_track_codes(mode: str, all_codes: list, track_codes: list, exclude_codes: list) -> dict
```
**Description:** Builds error code tracking mapping based on mode and provided codes.

**Processing:**
- **"trackonly":** Returns mapping of only specified track_codes
- **Other modes:** Returns mapping of all codes except those in exclude_codes

**Returns:** Dictionary mapping error code indices to None

---

## 🔍 Utility Functions

### pdeathsig_wrapper
**File:** `src/utils/pdeathsig_wrapper.py`

Provides process death signal handling for child processes to ensure proper cleanup when the parent process is forcefully terminated.

#### Functions

##### `pdeathsig_preexec()`
```python
def pdeathsig_preexec() -> None
```
**Description:** Sets up parent death signal (SIGTERM) for child processes to ensure automatic cleanup when the parent Controller process is forcefully killed.

**Behavior:**
- **Normal Shutdown:** During graceful shutdown, this function has no effect as the Controller properly terminates child processes
- **Forced Termination:** When the Controller is forcefully killed (e.g., `kill -9`, system crash), child processes receive SIGTERM and can clean up resources
- **Orphan Prevention:** Prevents child processes from becoming orphaned and continuing to run after the parent dies

**Implementation:** Uses `prctl(PR_SET_PDEATHSIG, SIGTERM)` to register the death signal before process execution.

**Usage:**
```python
subprocess.Popen(
    command,
    preexec_fn=pdeathsig_preexec
)
```

**Use Cases:**
- eBPF tool processes supervised by Controller
- Any subprocess that needs automatic cleanup on parent termination
- Preventing resource leaks when the main process is killed unexpectedly

### set_thread_name
**File:** `src/Controller.py`

Utility function for setting thread names visible in system monitoring tools.

#### Functions

##### `set_thread_name(name: str)`
```python
def set_thread_name(name: str) -> None
```
**Parameters:**
- `name` (str): Thread name to set (truncated to 15 characters due to Linux kernel limit)

**Description:** Sets the thread name visible in system monitoring tools like htop (press H to show threads) and ps. This helps with debugging and monitoring by making it easier to identify specific threads in the system.

**Implementation:** Uses `prctl(PR_SET_NAME)` syscall through ctypes to set the thread name at the kernel level.

**Usage:**
```python
set_thread_name("EventDispatcher")  # Makes thread visible as "EventDispatcher" in htop
```

**Thread Names Used in AOD:**
- `"Controller"` - Main controller thread
- `"ProcessSupervisor"` - Thread supervision coordination
- `"EventDispatcher"` - Event processing from eBPF
- `"AnomalyWatcher"` - Anomaly detection and analysis
- `"LogCollector"` - Diagnostic data collection
- `"SpaceWatcher"` - Disk space monitoring
- `"{tool_name}_Supervisor"` - eBPF tool supervision (e.g., "smbslower_Supervisor")

**Benefits:**
- Easy identification of threads in system monitoring tools
- Improved debugging and troubleshooting experience
- Better visibility into AOD system components during operation

### config_schema
**File:** `src/utils/config_schema.py`

Defines configuration data structures for the AOD system.

#### Data Classes

##### `AnomalyConfig`
```python
@dataclass(slots=True, frozen=True)
class AnomalyConfig:
    type: str
    tool: str
    acceptable_count: int
    default_threshold_ms: Optional[int] = None
    track: dict[int, Optional[int]] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)
```
**Description:** Configuration for individual anomaly detection rules.

##### `GuardianConfig`
```python
@dataclass(slots=True, frozen=True)
class GuardianConfig:
    anomalies: dict[str, AnomalyConfig]
```
**Description:** Configuration container for all anomaly detection rules.

##### `WatcherConfig`
```python
@dataclass(slots=True, frozen=True)
class WatcherConfig:
    actions: list[str]
```
**Description:** Configuration for watcher actions.

##### `Config`
```python
@dataclass(slots=True, frozen=True)
class Config:
    watch_interval_sec: int
    aod_output_dir: str
    watcher: WatcherConfig
    guardian: GuardianConfig
    cleanup: dict
    audit: dict
```
**Description:** Top-level configuration object for the entire AOD system.

### anomaly_type
**File:** `src/utils/anomaly_type.py`

Defines enumeration for anomaly types and mappings.

#### Enums

##### `AnomalyType`
```python
class AnomalyType(Enum):
    LATENCY = "latency"
    ERROR = "error"
    # Add more types as needed
```

#### Mappings

##### `ANOMALY_TYPE_TO_TOOL_ID`
```python
ANOMALY_TYPE_TO_TOOL_ID = {
    AnomalyType.LATENCY: 0,
    AnomalyType.ERROR: -1,  # fill correct value here
    # Add more as needed
}
```
**Description:** Maps anomaly types to their corresponding eBPF tool IDs for event filtering.

---

## 🌐 Global Variables and Constants

### shared_data
**File:** `src/shared_data.py`

Contains global constants, data structures, and mappings shared across all AOD components.

#### Shared Memory Configuration

##### Ring Buffer Constants
```python
SHM_NAME = "/bpf_shm"                    # Shared memory segment name for eBPF communication
HEAD_TAIL_BYTES = 8                     # Bytes for head/tail pointers (x64 architecture)
MAX_ENTRIES = 2048                      # Maximum entries in ring buffer
PAGE_SIZE = 4096                        # Memory page size (4KB)
SHM_SIZE = (MAX_ENTRIES + 1) * PAGE_SIZE # Total shared memory size (~8.4MB)
SHM_DATA_SIZE = SHM_SIZE - 2 * HEAD_TAIL_BYTES # Available data space
```

**Purpose:** Defines the ring buffer used for high-performance communication between eBPF programs and EventDispatcher.

**Architecture Notes:**
- **Producer-Consumer Model:** eBPF programs (producers) write events, EventDispatcher (consumer) reads them
- **Memory Layout:** 
  - **Head Pointer** (8 bytes): Points to next write position (managed by eBPF)
  - **Tail Pointer** (8 bytes): Points to next read position (managed by EventDispatcher)
  - **Data Area** (SHM_DATA_SIZE bytes): Circular buffer for event storage
- **Ring Buffer Logic:**
  - **Available Data:** `head - tail` (or wrap-around calculation)
  - **Wrap-around:** When tail/head reach end, they wrap to beginning of data area
- **Synchronization:** Head/tail pointers provide lock-free communication between eBPF and userspace
- **Memory Mapping:** Uses `/dev/shm` for shared memory between processes

##### Timing Constants
```python
MAX_WAIT = 0.005                        # 5ms wait time in event processing
```

**Purpose:** Used by EventDispatcher and AnomalyWatcher to accumulate events before processing. 
- If the Event Dispatcher finds out that there are 10 events or 3 seconds have passed, it will wait for MAX_WAIT seconds to allow events to accumulate before processing.
- The Anomaly Watcher waits for the event queue to be non empty. When non empty, it will drain the queue for MAX_WAIT seconds to allow more batches to accumulate before processing.

#### SMB Command Mappings

##### `ALL_SMB_CMDS`
```python
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
    "SMB2_SERVER_TO_CLIENT_NOTIFICATION": 19,
})
```

**Purpose:** 
- Maps SMB2 command names to numeric IDs used in eBPF programs
- Used by ConfigManager for command validation and threshold mapping
- Used by LatencyAnomalyHandler for threshold lookups

**Features:**
- **Immutable:** Uses MappingProxyType to prevent accidental modification
- **Bidirectional:** Can map names to IDs and vice versa
- **Complete Coverage:** Includes all SMB2 commands supported by the system

#### Error Code Mappings

##### `ALL_ERROR_CODES`
```python
ALL_ERROR_CODES = list(errno.errorcode.values())  # All system error codes
```

**Purpose:** 
- Provides complete list of system error codes for validation
- Used by ConfigManager for error anomaly configuration
- Used by ErrorAnomalyHandler for error detection

**Source:** Derived from Python's errno module for system-wide error code consistency.

#### Data Structures

##### Task Constants
```python
TASK_COMM_LEN = 16                      # Task command name length (Linux kernel limit)
```

**Purpose:** Defines the maximum length for process command names, matching the Linux kernel's TASK_COMM_LEN.

##### Event Structure (C Compatible)
```python
class Event(ctypes.Structure):
    _fields_ = [
        ("pid", ctypes.c_int),                    # Process ID
        ("cmd_end_time_ns", ctypes.c_ulonglong), # Command completion time (nanoseconds)
        ("session_id", ctypes.c_ulonglong),      # SMB session identifier
        ("mid", ctypes.c_ulonglong),             # SMB message ID
        ("smbcommand", ctypes.c_ushort),         # SMB command type (maps to ALL_SMB_CMDS)
        ("metric", Metrics),                     # Union of latency_ns or retval
        ("tool", ctypes.c_ubyte),                # eBPF tool identifier
        ("is_compounded", ctypes.c_ubyte),       # SMB compound request flag
        ("task", ctypes.c_char * TASK_COMM_LEN), # Process command name
    ]
```

**Purpose:** 
- Defines the C structure layout for events passed from eBPF to Python
- Must match exactly with the eBPF program's event structure
- Used for direct memory casting from shared memory

##### Metrics Union
```python
class Metrics(ctypes.Union):
    _fields_ = [
        ("latency_ns", ctypes.c_ulonglong),  # Latency in nanoseconds (for latency events)
        ("retval", ctypes.c_int)            # Return value (for error events)
    ]
```

**Purpose:** 
- Allows the same memory location to store either latency or error data
- Saves memory by sharing space between mutually exclusive data types
- Used within the Event structure for metric data

##### NumPy Event Format
```python
event_dtype = np.dtype([
    ("pid", np.int32),
    ("cmd_end_time_ns", np.uint64),
    ("session_id", np.uint64),
    ("mid", np.uint64),
    ("smbcommand", np.int16),
    ("metric_latency_ns", np.uint64),    # Note: Only latency field exposed
    ("tool", np.uint8),
    ("is_compounded", np.uint8),
    ("task", f"S{TASK_COMM_LEN}"),
], align=True)
```

**Purpose:** 
- Defines NumPy structured array format for efficient batch processing
- Used by EventDispatcher for parsing raw bytes into structured arrays
- Used by AnomalyWatcher for vectorized anomaly detection
- **Important:** Must have the same memory layout as the Event ctypes structure

**Key Features:**
- **Alignment:** Uses `align=True` for proper memory alignment
- **Type Safety:** Provides type information for NumPy operations
- **Performance:** Enables vectorized operations on event batches
- **Compatibility:** Memory layout matches the C Event structure exactly, The `align=True` parameter ensures this

#### Usage Patterns

**EventDispatcher:**
- Uses `SHM_NAME` for shared memory segment identification
- Uses `SHM_SIZE` and `SHM_DATA_SIZE` for memory mapping configuration
- Uses `HEAD_TAIL_BYTES` for head/tail pointer management
- Uses `Event` structure for casting raw shared memory bytes to Python objects
- Uses `event_dtype` for creating NumPy arrays from parsed events
- Uses `MAX_WAIT` for polling sleep intervals

**AnomalyWatcher:**
- Uses `event_dtype` for processing event batches from EventDispatcher
- Uses `MAX_WAIT` for polling intervals between batch processing
- Passes structured NumPy arrays to anomaly handlers

**LatencyAnomalyHandler:**
- Uses `ALL_SMB_CMDS` for threshold lookup array sizing: `np.full(len(ALL_SMB_CMDS) + 1, 0, dtype=np.uint64)`
- Uses SMB command IDs as indices for threshold lookups
- Processes `event_dtype` structured numpy arrays (`events_batch`) for vectorized anomaly detection
- Accesses `smbcommand` and `metric_latency_ns` fields from event in `events_batches` array

**Controller:**
- Uses `ALL_SMB_CMDS` for eBPF tool command generation
- Builds SMB command lists for smbsloweraod process arguments
- Converts command names to IDs for eBPF program configuration
- Example: `track_cmds = ",".join(str(cmd_id) for cmd_id in ALL_SMB_CMDS.keys())`

**ConfigManager:**
- Uses `ALL_SMB_CMDS` for SMB command validation during configuration parsing
- Uses `ALL_ERROR_CODES` for error code validation in error anomaly configuration
- Validates that configured commands exist in the global mapping
- Maps command names to IDs for threshold configuration

**eBPF Programs (smbsloweraod):**
- Uses `Event` structure layout for writing events to shared memory
- Uses `SHM_NAME` for shared memory segment access
- Uses `SHM_SIZE` and related constants for ring buffer management
- Writes events using head pointer, EventDispatcher reads using tail pointer

**Component Interaction Flow:**
1. **Configuration:** ConfigManager validates commands/codes against shared mappings
2. **Tool Startup:** Controller uses command mappings to configure eBPF programs
3. **Event Generation:** eBPF programs write Event structures to shared memory
4. **Event Processing:** EventDispatcher reads and converts to NumPy arrays
5. **Anomaly Detection:** Handlers use mappings for efficient threshold/error lookups
6. **Cross-Component:** All components share the same data definitions for consistency

### AnomalyWatcher Registries
**File:** `src/AnomalyWatcher.py`

#### Handler Registry
```python
ANOMALY_HANDLER_REGISTRY = {
    AnomalyType.LATENCY: LatencyAnomalyHandler,
    AnomalyType.ERROR: ErrorAnomalyHandler,
    # Add more types here as needed
}
```
**Description:** Global registry mapping anomaly types to their handler classes. Used during initialization to instantiate the appropriate handlers based on configuration.

---

##  Data Structures

### Event Structure (NumPy)
**File:** `src/shared_data.py`

NumPy structured array format used by EventDispatcher and AnomalyWatcher:

```python
event_dtype = np.dtype([
    ("pid", np.int32),                 # Process ID
    ("cmd_end_time_ns", np.uint64),    # Command completion time (nanoseconds)
    ("session_id", np.uint64),         # SMB session identifier
    ("mid", np.uint64),                # SMB message ID
    ("smbcommand", np.int16),          # SMB command type (maps to ALL_SMB_CMDS)
    ("metric_latency_ns", np.uint64),  # Latency in nanoseconds
    ("tool", np.uint8),                # eBPF tool identifier
    ("is_compounded", np.uint8),       # SMB compound request flag
    ("task", f"S{TASK_COMM_LEN}"),     # Process command name (16 bytes)
], align=True)
```

### Anomaly Action Structure
Standard anomaly action format passed from AnomalyWatcher to LogCollector:

```python
{
    'type': AnomalyType,    # Anomaly type enum (AnomalyType.LATENCY or AnomalyType.ERROR)
    'timestamp': int        # Event timestamp in nanoseconds (used as batch_id)
}
```

---

## 🧪 Test Suite

This section describes the test suite that validates system functionality. Tests are located in the `tests/` directory.

### Core Component Tests

#### test_controller.py
Tests the main Controller class initialization, configuration loading, and graceful shutdown procedures.

#### test_event_dispatcher.py
Tests the EventDispatcher event processing pipeline, filtering logic, and queue management.

#### test_anomaly_watcher.py
Tests the AnomalyWatcher anomaly detection system and handler registry management.

#### test_log_collector.py
Tests the LogCollector diagnostic collection workflow and quick action execution.

#### test_space_watcher.py
Tests the SpaceWatcher disk space monitoring and threshold alert generation.

#### test_config_manager.py
Tests configuration file parsing, schema validation, and dynamic configuration updates.

#### test_shared_data.py
Tests shared data structures, thread safety, and SMB command mappings.

### Handler Tests

#### test_handlers.py
Tests all quick action handlers (CIFS stats, debug data, dmesg, journalctl, mounts, SMB info, syslogs) and anomaly handlers (error, latency).

### Utility Tests

#### test_utils.py
Tests utility functions including anomaly type enums, configuration schema utilities, and process death signal handling.

#### test_base.py
Tests abstract base classes for anomaly handlers and quick actions.

### Integration Tests

#### compare.py
Comparison utilities for validating test outputs and consistency across test runs.

#### csv_range_compare.py
CSV data range comparison for performance testing and data consistency validation.

#### disk_monitor.py
Disk monitoring test utilities for validating disk space tracking and alerts.

#### disk_plot.py
Disk usage visualization utilities for testing and visual validation of monitoring data.

#### monitor.py
General monitoring test framework for integration tests and system monitoring validation.

### Running Tests

To run the complete test suite:

```bash
# Run all tests
python -m pytest tests/

# Run specific test files
python -m pytest tests/test_controller.py
python -m pytest tests/test_handlers.py

# Run with coverage
python -m pytest tests/ --cov=src/

# Run with verbose output
python -m pytest tests/ -v
```

---
