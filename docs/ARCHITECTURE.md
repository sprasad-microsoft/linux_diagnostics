# Linux Diagnostics Controller (AODv2) - Architecture Guide

## 🏗️ System Architecture Overview

AODv2 is a sophisticated real-time monitoring and diagnostics system for Linux environments, optimized for SMB/CIFS workloads. The architecture uses a hybrid process and threading model, combining a central multi-threaded Python application with external eBPF processes for high-performance data collection. This design implements a producer-consumer pattern where the eBPF processes produce event data that is consumed and analyzed by specialized threads within the main application, enabling powerful, automated diagnostics.

## 🔧 Core Components

### 1. Controller (Main Orchestrator)
**File:** `src/Controller.py`

The Controller serves as the central coordinator and process supervisor:

- **Primary Responsibilities:**
  - Configuration management and validation
  - Component lifecycle management (startup/shutdown)
  - Thread supervision with automatic restart capabilities
  - Signal handling for graceful shutdown
  - Resource cleanup and error recovery

- **Threading Model:**
  - Runs in the main thread
  - Creates and manages dedicated threads for each component
  - Uses thread-safe queues for inter-component communication
  - Implements graceful shutdown with sentinel values

### 2. EventDispatcher (Data Ingestion)
**File:** `src/EventDispatcher.py`

Handles low-level event collection from eBPF tools via shared memory ring buffer:

- **Core Functions:**
  - Polls shared memory ring buffer written by eBPF programs
  - Converts raw C structs to Python numpy arrays
  - Feeds processed events into the event queue for analysis
  - Handles buffer overflow and data loss scenarios

- **Performance Characteristics:**
  - Runs in dedicated thread for non-blocking operation
  - Optimized for high-throughput event processing from ring buffer
  - Automatic restart on failures

### 3. AnomalyWatcher (Intelligence Engine)
**File:** `src/AnomalyWatcher.py`

The core intelligence component that analyzes events for anomalies:

- **Processing Model:**
  - Batch processing with configurable intervals (default: 1 second from `watch_interval_sec`)
  - Drains event queue and processes events in batches
  - Applies specialized anomaly detection algorithms
  - Triggers diagnostic collection when anomalies are detected

- **Anomaly Detection:**
  - **Latency Analysis:** Threshold-based detection per SMB command
  - **Error Analysis:** Pattern recognition for error codes (placeholder implementation)
  - **Emergency Detection:** Immediate triggers for critical thresholds

### 4. LogCollector (Diagnostic Engine)
**File:** `src/LogCollector.py`

Executes diagnostic collection with async task management:

- **Execution Model:**
  - Async event loop with semaphore-bounded concurrency
  - Parallel execution of QuickActions (hardcoded: 4 concurrent tasks)
  - Structured output organization with timestamp-based directories

- **Collection Pipeline:**
  - Receives anomaly events from AnomalyWatcher
  - Executes relevant QuickActions based on configuration
  - Compresses collected data using zstd compression
  - Manages output directory structure

### 5. SpaceWatcher (Maintenance)
**File:** `src/SpaceWatcher.py`

Autonomous cleanup and maintenance service:

- **Cleanup Strategies:**
  - **Size-based:** Removes logs when total size exceeds limits
  - **Age-based:** Removes logs older than configured maximum age
  - **Intelligent prioritization:** Preserves recent and critical logs

- **Monitoring:**
  - Periodic disk usage assessment
  - Configurable cleanup intervals
  - Automatic log rotation

## 📊 Data Flow Architecture

**Processing Pipeline:**
1. **eBPF Programs** (Kernel Space) → Write events to shared memory
2. **Ring Buffer** (Shared Memory) → Lock-free communication channel
3. **EventDispatcher** → Polls ring buffer, converts C structs to NumPy arrays
4. **Event Queue** → Thread-safe queue for processed events
5. **AnomalyWatcher** → Batch analysis of events from queue
6. **Anomaly Action Queue** → Queue for triggered diagnostic actions
7. **LogCollector** → Async execution of QuickActions (log collection)
8. **Diagnostic Output Files** → Compressed logs and diagnostic data

**Key Communication Channels:**
- **Shared Memory Ring Buffer:** eBPF ↔ EventDispatcher
- **Event Queue:** EventDispatcher → AnomalyWatcher  
- **Anomaly Action Queue:** AnomalyWatcher → LogCollector

## 🧵 Threading Model

### Process and Thread Architecture
- **Main Process:** Python application with multi-threaded components
- **External Processes:** eBPF programs running as separate supervised processes
- **Main Thread:** Controller (coordination and supervision)
- **Worker Threads:**
  - EventDispatcher thread
  - AnomalyWatcher thread
  - LogCollector thread (async event loop)
  - SpaceWatcher thread

### Process Management
- **eBPF Process Supervision:** Controller spawns and monitors eBPF tool processes
- **Process Restart:** Automatic restart of failed eBPF processes
- **Inter-Process Communication:** Shared memory ring buffer for high-performance data transfer
- **Process Isolation:** eBPF tools run independently from Python application

### Inter-Thread Communication
- **Event Queue:** EventDispatcher → AnomalyWatcher
- **Anomaly Action Queue:** AnomalyWatcher → LogCollector
- **Shared Data:** Configuration and state management

### Synchronization
- Thread-safe queues for data passing
- Sentinel values for graceful shutdown
- Exception propagation for error handling
- Lock-free ring buffer for eBPF communication

## 🔍 Anomaly Detection Algorithms

### Latency Detection
```python
# Configurable per-command thresholds (from config file)
# Converted to nanoseconds for comparison
threshold_lookup = np.full(len(ALL_SMB_CMDS) + 1, 0, dtype=np.uint64)
for smb_cmd_id, threshold in config.track.items():
    threshold_lookup[smb_cmd_id] = threshold * 1000000  # ms to ns

# Batch-based analysis
anomaly_count = np.sum(
    events_batch["metric_latency_ns"] >= threshold_lookup[events_batch["smbcommand"]]
)
max_latency = np.max(events_batch["metric_latency_ns"])

# Trigger conditions
return anomaly_count >= acceptable_count or max_latency >= 1e9  # 1 second
```

### Error Detection
```python
# Currently placeholder implementation
class ErrorAnomalyHandler(AnomalyHandler):
    def detect(self, events_batch: np.ndarray) -> bool:
        return False  # Not yet implemented
```

### Emergency Detection
- **Immediate triggers:** Any operation exceeding 1-second (1e9 nanoseconds) threshold
- **Batch-based triggers:** When `anomaly_count >= acceptable_count` for configured thresholds


## 🎯 QuickActions System

### QuickAction Architecture
**Base Class:** `src/base/QuickAction.py`

All diagnostic collectors inherit from the QuickAction base class:

```python
class QuickAction(ABC):
    def __init__(self, batches_root: str, log_filename: str):
        """Initialize with output directory and log filename"""
        
    @abstractmethod
    def get_command(self) -> tuple[list[str], str]:
        """Return command and command type ('cat' or 'cmd')"""
        
    async def execute(self, batch_id: str) -> None:
        """Execute diagnostic collection asynchronously"""
```

**Architecture Pattern:**
- **Individual QuickActions:** Only define what command to run via `get_command()`
- **Base Class Execution:** The base `QuickAction.execute()` method handles the actual command execution
- **Command Definition vs. Execution:** Subclasses specify commands, base class executes them

**Command Types:**
- **"cat" commands:** Direct file reads (e.g., `/proc/fs/cifs/DebugData`)
- **"cmd" commands:** Shell command execution (e.g., `journalctl`, `dmesg`)

**Key Features:**
- **Async execution** with graceful error handling via base class
- **Automatic output directory creation** with timestamp-based batch IDs
- **Performance metrics tracking** (execution count, timing, success rates)
- **Fail-safe operation** - individual action failures don't stop other actions

### Available QuickActions

**Command-Based Actions:**
- **DmesgQuickAction:** Kernel messages via `journalctl -k` (last N seconds)
- **JournalctlQuickAction:** Systemd journal entries (last N seconds)  
- **SysLogsQuickAction:** System log tail (configurable line count, default: 100)

**File-Based Actions (cat commands):**
- **DebugDataQuickAction:** SMB debug data from `/proc/fs/cifs/DebugData`
- **CifsstatsQuickAction:** CIFS statistics from `/proc/fs/cifs/Stats`
- **MountsQuickAction:** Mount information from `/proc/mounts`
- **SmbinfoQuickAction:** SMB connection information

**Implementation Details:**
- **Time-based filtering:** DmesgQuickAction and JournalctlQuickAction use `anomaly_interval` parameter
- **Configurable parameters:** SysLogsQuickAction accepts `num_lines` parameter  
- **Output structure:** Each action creates `{action_name}.log` in batch directory
- **Batch organization:** Outputs stored in `aod_quick_{timestamp}/` directories

## 🔧 Configuration System

### Configuration Architecture
**File:** `src/ConfigManager.py`

- **YAML-based configuration** with schema validation
- **Runtime configuration access** through dataclasses
- **Dataclass-based schema** for type safety and validation

### Configuration Sections
- **Monitoring:** Watch intervals, thresholds, and detection parameters
- **Actions:** QuickAction selection and configuration
- **Cleanup:** Disk space management and log retention
- **Audit:** Logging and monitoring configuration

##  Performance Characteristics

### Scalability
- **Event Processing:** High-throughput event processing via shared memory ring buffer
- **Memory Usage:** Minimal footprint with efficient data structures (NumPy arrays)
- **CPU Overhead:** Optimized with async processing and batch operations
- **Disk I/O:** Optimized with zstd compression and batch operations

### Reliability
- **Automatic Recovery:** Thread restart on failures
- **Data Integrity:** No event loss with ring buffer design
- **Graceful Degradation:** Individual action failures don't stop other actions
- **Error Handling:** Comprehensive exception handling and logging

## 🔐 Security Considerations

### Privilege Management
- **Root Access:** Required for eBPF program loading (enforced via `os.geteuid()` check)
- **File Permissions:** Output directory management
- **Process Isolation:** eBPF tools run as separate processes

### Data Protection
- **Restricted Access:** Diagnostic outputs stored in configurable directories
- **Process Separation:** eBPF and Python processes run independently

## 📈 Monitoring and Observability

### Built-in Monitoring
- **Performance Metrics:** All components track execution metrics (timing, success rates, throughput)
- **Component Health:** Automatic thread supervision with restart capabilities
- **Queue Metrics:** Event queue processing rates and batch sizes
- **Debug Logging:** Comprehensive debug output when `__debug__` is enabled

### Syslog Integration
- **Anomaly Alerts:** Anomaly detection events logged to syslog with `LOG_ALERT` priority
- **Component Restarts:** Thread/process restart events logged with `LOG_WARNING` priority
- **System Integration:** Standard syslog integration for system-wide monitoring

**Syslog Messages:**
```
AOD detected anomaly: {anomaly_type} with {event_count} events
AOD component {component_name} restarted due to unexpected exit
```

## 🔄 Deployment Architecture

### Git-based Deployment
- **Source Code Deployment:** Clone repository and run directly from source
- **Manual Configuration:** Configuration file located at `config/config.yaml`
- **Direct Execution:** Run `sudo python3 src/Controller.py` from project root
- **Root User Requirement:** Must run as root for eBPF program access

### Prerequisites
- **Python Version:** Python 3.9 or higher (based on project configuration)
- **Root Access:** Required for eBPF program access and system monitoring
- **Linux Environment:** Designed for Linux systems with kernel 5.15+ eBPF support (6.8+ required for future eBPF scripts)

### Installation Flow
1. **Python Version Check:** Verify Python 3.9+ is available: `python3 --version`
2. **Clone Repository:** `git clone <repository-url>`
3. **Install Dependencies:** `pip3 install -r requirements.txt`
4. **Configuration Setup:** Edit `config/config.yaml` as needed

### Runtime Startup (when running `sudo python3 src/Controller.py`)
1. **Root Access Validation:** Runtime check enforced via `os.geteuid()`
2. **Configuration Loading:** Load and validate `config/config.yaml`
3. **eBPF Program Execution:** Automatic eBPF program loading and shared memory setup
4. **Component Startup:** Automatic component supervision and event processing

This architecture provides a robust foundation for real-time system monitoring and automated diagnostics collection, designed to operate reliably in production environments while maintaining minimal system impact.
