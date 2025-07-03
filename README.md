# Linux Diagnostics Controller (AODv2)

The Linux Diagnostics Controller, also known as **AODv2** (Anomaly On-Demand version 2), is an advanced production-ready system designed for real-time monitoring and automated diagnostics collection in Linux environments. 

Built specifically for SMB/CIFS workloads, AODv2 continuously monitors system performance using lightweight eBPF tools, detects anomalies as they occur, and automatically triggers comprehensive diagnostic data collection. This proactive approach enables rapid troubleshooting and root cause analysis without manual intervention.

## 🎯 Key Features

- **Real-time Anomaly Detection**: Sub-second detection of latency spikes and error patterns
- **Automated Diagnostics**: Instant collection of relevant system data when anomalies occur
- **Low Overhead Monitoring**: eBPF-based tools with minimal performance impact
- **Configurable Thresholds**: Customizable detection parameters for different environments
- **Intelligent Cleanup**: Automatic log rotation and disk space management

## 🏗️ System Architecture

AODv2 implements a sophisticated multi-threaded architecture designed for high-performance real-time monitoring and automated response capabilities. The system operates as a coordinated set of specialized components, each running in dedicated threads to ensure optimal performance and reliability.

### Core Components

AODv2 consists of several components, with the `EventDispatcher`, `AnomalyWatcher`, `LogCollector`, and `SpaceWatcher` each running in a dedicated thread for concurrent processing.

- **ConfigManager**: Validates and parses the configuration YAML into Python dataclasses, providing runtime access to configuration throughout the system.

- **Controller**: The main orchestrator running in the primary process. It manages the startup, configuration, and graceful shutdown of the AODv2 service. It coordinates all components, supervises thread execution with automatic restart capabilities, and ensures a smooth shutdown process by signaling all threads to terminate and cleaning up resources.

- **EventDispatcher**: Polls the C ring buffer and drains all events from eBPF tools. Parses raw C structs into Python numpy struct arrays and sends them to the `eventQueue`. Runs in a dedicated thread with exception handling that propagates failures to the Controller for automatic restart.

- **AnomalyWatcher**: Registers as a consumer on the `eventQueue`. Sleeps for a configurable interval (`watch_interval_sec`), then wakes up and drains the queue. Computes masks to separate events by anomaly type and conducts anomaly analysis using specialized handlers. Queues anomaly events to the LogCollector's `anomalyActionQueue`.

- **LogCollector**: Consumes the `anomalyActionQueue` using an async event loop. For each anomaly event, it executes QuickActions using an async semaphore-bounded task system (`max_concurrent_tasks=4`) rather than a traditional threadpool. Compresses collected logs using fast zstd compression.

- **SpaceWatcher**: An autonomous cleanup service that periodically monitors disk usage. It performs cleanup based on two main strategies:
  - **Size-based cleanup**: Triggers when total log size exceeds a configured limit.
  - **Age-based cleanup**: Removes logs older than a configured maximum age.

### Component Communication

The architecture uses a producer-consumer model with thread-safe queues for inter-component communication:

- **Event Queue**: High-throughput queue carrying raw monitoring events from EventDispatcher to AnomalyWatcher
- **Anomaly Action Queue**: Task queue carrying anomaly events from AnomalyWatcher to LogCollector

### Anomaly Event Structure

Anomaly events use a standardized format for communication between components:
```python
{
    "anomaly": AnomalyType.LATENCY,  # Enum value (LATENCY, ERROR, etc.)
    "timestamp": 1640995200000000000  # Nanoseconds since epoch (used as batch_id)
}
```

The `timestamp` field serves dual purposes:
- Unique identifier for the anomaly event
- Directory name for log collection (`aod_{timestamp}/`)

### Thread Management

Each component runs in its own dedicated thread with proper lifecycle management:
- Graceful startup sequencing with dependency resolution
- **Graceful Shutdown**: On shutdown, the Controller sends sentinel values (e.g., `None`) to all queues, signaling consumer threads to stop processing. It then waits for all threads to join, ensuring that all in-flight events are processed and resources are cleaned up properly before exiting.
- Signal handling for service control and emergency stops
- Thread naming for easy identification in system monitoring tools
- Automatic restart of threads/processes if they stop unexpectedly


### Stream Processing

**Event Flow**:
1. **Kernel Events**: eBPF programs capture SMB operations and write to the shared memory ring buffer.
2. **EventDispatcher**: Polls the ring buffer, converts C structs to numpy arrays, and queues events.
3. **Batch Processing**: AnomalyWatcher processes events in configurable intervals (`watch_interval_sec`)
4. **Anomaly Analysis**: Specialized handlers analyze events (against thresholds for Latency Anomaly Handler)
5. **Action Triggering**: Anomaly events queued for diagnostic collection
6. **Log Collection**: Async execution of QuickActions with semaphore-based concurrency control

**Processing Characteristics**:
- **No Event Loss**: Ring buffer design ensures all events are captured and analyzed
- **Configurable Intervals**: Default 1-second batch processing with sub-second detection capability
- **Automatic Recovery**: Thread supervision with automatic restart on failures

### Anomaly Detection Algorithms

**Latency Detection**:
- Per-command threshold evaluation (SMB2_READ, SMB2_WRITE, etc.)
- Configurable acceptable violation counts within batch intervals
- Emergency detection for operations exceeding 1-second thresholds (immediate trigger)

### Diagnostic Collection Pipeline

**Asynchronous Collection System**:
- Semaphore-bounded async tasks (default: 4 concurrent collections)
- QuickAction execution for targeted diagnostic gathering
- Zstd compression
- Structured output organization with timestamp-based batch directories

## 📁 Project Structure

```
linux_diagnostics/
├── src/                          # Core application source code
│   ├── Controller.py             # Main service controller and orchestrator
│   ├── AnomalyWatcher.py         # Anomaly detection engine
│   ├── EventDispatcher.py        # Event routing from eBPF to Python
│   ├── LogCollector.py           # Diagnostic data collection and compression
│   ├── SpaceWatcher.py           # Disk usage monitoring and cleanup
│   ├── ConfigManager.py          # Configuration loading and validation
│   ├── shared_data.py            # Shared constants (e.g., SMB commands, error codes)
│   ├── base/                     # Abstract base classes for core components
│   │   ├── AnomalyHandlerBase.py # Interface for anomaly handlers
│   │   └── QuickAction.py        # Interface for diagnostic actions
│   ├── handlers/                 # Concrete implementations of handlers and actions
│   │   ├── latency_anomaly_handler.py    # Logic for latency anomaly detection
│   │   ├── error_anomaly_handler.py      # Logic for error anomaly detection
│   │   └── ...                   # Implementations of all QuickActions
│   ├── utils/                    # Utility modules and helper functions
│   │   ├── anomaly_type.py       # Enum for anomaly types
│   │   └── config_schema.py      # Dataclasses for configuration schema
│   └── bin/                      # Compiled eBPF binaries
│       └── smbsloweraod          # eBPF tool for monitoring SMB latency
├── config/                       # Configuration files
│   └── config.yaml               # Main configuration file (user-editable)
├── packages/                     # Package building scripts (DEB and RPM)
├── tests/                        # Test suite for the application
│   ├── test_controller.py        # Unit tests for the Controller
│   └── ...                       # Other unit and integration tests
├── linux_diagnostics.service     # Systemd service definition file
├── Makefile                      # Build automation for packages and code quality
├── pyproject.toml                # Python project configuration (PEP 621)
├── USAGE.md                      # Detailed usage and configuration guide
└── README.md                     # This file (overview and architecture)
```

## 🚀 Getting Started

### Installation

#### From Packages (Recommended)  (not yet implemented)

**Debian/Ubuntu:**
```bash
# Build DEB package
make debian
sudo dpkg -i ../linux_diagnostics_1.0-1_all.deb
sudo apt-get install -f  # Resolve dependencies if needed
```

**RHEL/CentOS/Fedora:**
```bash
# Build RPM package
make rpm
sudo rpm -ivh ~/rpmbuild/RPMS/noarch/linux_diagnostics-1.0-1.noarch.rpm
```

#### From Source

```bash
# Clone repository
git clone <repository-url>
cd linux_diagnostics

# Install dependencies from pyproject.toml
pip3 install .

# Configure (see configuration section below) and install the service (not yet implemented)
sudo cp config/config.yaml /etc/linux_diagnostics/
sudo cp linux_diagnostics.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable linux_diagnostics.service
```

### Basic Usage (not yet implemented)

**Start the service:**
```bash
sudo systemctl start linux_diagnostics.service
```

**Check service status:**
```bash
sudo systemctl status linux_diagnostics.service
```

**View logs:**
```bash
sudo journalctl -u linux_diagnostics.service -f
```

**Stop the service:**
```bash
sudo systemctl stop linux_diagnostics.service
```

### How to run AOD as a python code


```
cd /path/to/linux_diagnostics
sudo python3 src/Controller.py
```

**Run AOD in different log levels**
```
cd /path/to/linux_diagnostics
sudo AOD_LOG_LEVEL=DEBUG python3 src/Controller.py
```

**Run AOD with minimal logging/metric calculation overhead**
```
cd /path/to/linux_diagnostics
sudo python3 -O src/Controller.py
```


## ⚙️ Configuration

The main configuration file is located at `config/config.yaml`. Below is an example demonstrating key sections. The configuration is loaded and validated at startup.

```yaml
# Monitoring frequency and log output directory
watch_interval_sec: 1
aod_output_dir: /var/log/aod

# --- Anomaly Detection ---
guardian:
  anomalies:
    # Latency anomaly detection
    latency:
      type: "Latency"
      tool: "smbslower"
      mode: "all"
      acceptable_count: 10
      default_threshold_ms: 20
      track_commands:
        - command: SMB2_WRITE
          threshold: 50
      actions:
        - dmesg
        - journalctl
        - debugdata
        - stats
        - mounts
        - smbinfo
        - syslogs

    # Error anomaly detection
    error:
      type: "Error"
      tool: "smbiosnoop"
      mode: "trackonly"
      acceptable_count: 10
      track_codes:
        - EACCES
        - EAGAIN
        - EIO
      actions:
        - dmesg
        - journalctl

# --- QuickActions ---
# Defines the complete list of available diagnostic actions.
watcher:
  actions:
    - tcpdump
    - dmesg
    - journalctl
    - debugdata
    - stats

# --- Log Cleanup ---
cleanup:
  cleanup_interval_sec: 60
  max_log_age_days: 2
  max_total_log_size_mb: 0.5

# --- Auditing ---
audit:
  enabled: true
```

### Configuration Explained

- **`watch_interval_sec`**: The frequency in seconds at which the `AnomalyWatcher` checks for new events. A lower value means faster detection but slightly higher CPU usage.
- **`aod_output_dir`**: The root directory where all diagnostic logs and collected data are stored.

- **`guardian`**: The main section for configuring all anomaly detection logic.
  - **`anomalies`**: A dictionary defining each specific anomaly to monitor.
    - **`type`**: Maps to a specific `AnomalyHandler` class (e.g., `"Latency"` maps to `LatencyAnomalyHandler`).
    - **`tool`**: The name of the eBPF executable that generates the monitoring data for this anomaly.
    - **`mode`**: Determines how events are filtered. `"all"` tracks everything, `"trackonly"` only includes items in the `track_` list, and `"excludeonly"` ignores them.
    - **`acceptable_count`**: The threshold for triggering an anomaly. For example, if more than 10 latency events occur in a `watch_interval_sec`, an anomaly is declared.
    - **`default_threshold_ms`**: (For latency) The default latency in milliseconds that is considered acceptable if a command-specific threshold is not set.
    - **`track_commands` / `track_codes`**: A list of specific SMB commands or error codes to monitor, often with custom thresholds.
    - **`actions`**: A list of `QuickActions` to execute *specifically* when this anomaly is triggered. These must be names defined in the global `watcher.actions` list.

- **`watcher`**: This section defines the master list of all available `QuickActions`.
  - **`actions`**: A complete list of all diagnostic actions (e.g., `dmesg`, `tcpdump`) that are available to be triggered by any anomaly. This list populates the available actions that can be referenced under `guardian.anomalies`.

- **`cleanup`**: Configures the `SpaceWatcher` for automated log management.
  - **`cleanup_interval_sec`**: How often the cleanup process runs.
  - **`max_log_age_days`**: The maximum number of days to keep log files before they are deleted.
  - **`max_total_log_size_mb`**: The maximum total size of the `aod_output_dir`. If this limit is exceeded, the oldest logs are deleted until the total size is under the limit.

- **`audit`**: Contains settings for internal system auditing.
  - **`enabled`**: If `true`, enables detailed logging for debugging and auditing the AOD system itself.

## 🚀 Advanced Usage and Development

For detailed instructions on performance testing, troubleshooting, and extending the system, please refer to the comprehensive **[USAGE.md](USAGE.md)** guide.
