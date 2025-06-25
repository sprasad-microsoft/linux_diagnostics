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

- **ConfigManager**: Validates and parses the configuration YAML into Python dataclasses, providing runtime access to configuration throughout the system.

- **Controller**: The main orchestrator running in the primary process (not a thread). Manages startup, configuration, and shutdown of the AODv2 service. It coordinates all components and ensures the service runs under desired constraints. Supervises thread execution with automatic restart capabilities for failed threads/processes.

- **EventDispatcher**: Polls the C ring buffer and drains all events from eBPF tools. Parses raw C structs into Python numpy struct arrays and sends them to the `eventQueue`. Runs in a dedicated thread with exception handling that propagates failures to the Controller for automatic restart.

- **AnomalyWatcher**: Registers as a consumer on the `eventQueue`. Sleeps for a configurable interval (`watch_interval_sec`), then wakes up and drains the queue. Computes masks to separate events by anomaly type and conducts anomaly analysis using specialized handlers. Queues anomaly events to the LogCollector's `anomalyActionQueue`.

- **LogCollector**: Consumes the `anomalyActionQueue` using an async event loop. For each anomaly event, it executes QuickActions using an async semaphore-bounded task system (`max_concurrent_tasks=4`) rather than a traditional threadpool. Compresses collected logs using fast zstd compression.

- **SpaceWatcher**: Autonomous cleanup service with configurable intervals (default: 60 seconds). Monitors disk usage and performs intelligent cleanup:
  - **Size-based cleanup**: Triggers when usage exceeds 90% of configured limit
  - **Age-based cleanup**: Removes logs older than `max_log_age_days` 
  - **Emergency mode**: More aggressive cleanup (80% threshold) when usage exceeds 95%
  - **Race condition prevention**: Only counts completed `.tar.zst` files for space calculations

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
- Coordinated shutdown with cleanup and resource deallocation
- Signal handling for service control and emergency stops
- Thread naming for easy identification in system monitoring tools
- Automatic restart of threads/processes if they stop unexpectedly

## 🔄 Real-Time Processing Pipeline

AODv2's real-time processing system is built around an efficient event streaming architecture with minimal kernel-user mode transitions.

### Event Collection Layer

**eBPF Monitoring Tools**:
- `smbsloweraod`: Kernel-level SMB command latency monitoring with microsecond precision
- `smbiosnoop`: Real-time SMB I/O and error code tracking  
- Custom eBPF programs for specific monitoring requirements

**Shared Memory Ring Buffer**:
- Zero-copy event transfer from kernel eBPF to user space
- Batch processing to minimize context switches
- Configurable buffer sizes for high-throughput workloads

### Stream Processing

**Event Flow**:
1. **Kernel Events**: eBPF programs capture SMB operations and write to shared memory ring buffer
2. **EventDispatcher**: Polls ring buffer, converts C structs to numpy arrays, queues events
3. **Batch Processing**: AnomalyWatcher processes events in configurable intervals (`watch_interval_sec`)
4. **Anomaly Analysis**: Specialized handlers analyze events against thresholds
5. **Action Triggering**: Anomaly events queued for diagnostic collection
6. **Log Collection**: Async execution of QuickActions with semaphore-based concurrency control

**Processing Characteristics**:
- **No Event Loss**: Ring buffer design ensures all events are captured and analyzed
- **Configurable Intervals**: Default 1-second batch processing with sub-second detection capability
- **Fault Tolerance**: Individual component failures don't stop the processing pipeline
- **Automatic Recovery**: Thread supervision with automatic restart on failures

### Anomaly Detection Algorithms

**Latency Detection**:
- Per-command threshold evaluation (SMB2_READ, SMB2_WRITE, etc.)
- Configurable acceptable violation counts within batch intervals
- Emergency detection for operations exceeding 1-second thresholds (immediate trigger)

**Error Pattern Detection**:
- Error code frequency analysis with configurable tracking lists
- Batch-based evaluation against acceptable error rates

### Diagnostic Collection Pipeline

**Asynchronous Collection System**:
- Semaphore-bounded async tasks (default: 4 concurrent collections)
- QuickAction execution for targeted diagnostic gathering
- Zstd compression for fast log archival (2-3x faster than gzip)
- Structured output organization with timestamp-based batch directories

## 📁 Project Structure

```
linux_diagnostics/
├── src/                          # Core application source code
│   ├── Controller.py             # Main service controller
│   ├── AnomalyWatcher.py         # Anomaly detection engine
│   ├── EventDispatcher.py       # Event routing and processing
│   ├── LogCollector.py           # Diagnostic data collection
│   ├── SpaceWatcher.py           # Disk usage monitoring and cleanup
│   ├── ConfigManager.py          # Configuration management
│   ├── shared_data.py            # Shared constants and data structures
│   ├── base/                     # Base classes and interfaces
│   │   ├── AnomalyHandlerBase.py # Abstract anomaly handler
│   │   └── QuickAction.py        # Base class for diagnostic actions
│   ├── handlers/                 # Anomaly handlers and quick actions
│   │   ├── latency_anomaly_handler.py    # Latency anomaly detection
│   │   ├── error_anomaly_handler.py      # Error anomaly detection
│   │   ├── DmesgQuickAction.py           # Kernel message collection
│   │   ├── JournalctlQuickAction.py      # System journal collection
│   │   ├── CifsstatsQuickAction.py       # CIFS statistics
│   │   ├── SmbinfoQuickAction.py         # SMB connection info
│   │   ├── MountsQuickAction.py          # Mount point information
│   │   ├── SysLogsQuickAction.py         # System log collection
│   │   └── DebugDataQuickAction.py       # Debug data aggregation
│   ├── utils/                    # Utility modules
│   │   ├── anomaly_type.py       # Anomaly type definitions
│   │   └── config_schema.py      # Configuration validation
│   └── bin/                      # Binary tools
│       └── smbsloweraod          # eBPF SMB latency monitor
├── config/                       # Configuration files
│   └── config.yaml               # Main configuration file
├── packages/                     # Package building scripts
│   ├── debian/                   # Debian package files
│   │   ├── control               # Package metadata
│   │   ├── postinst              # Post-installation script
│   │   ├── prerm                 # Pre-removal script
│   │   └── rules                 # Build rules
│   └── rpm/                      # RPM package files
│       ├── linux_diagnostics.spec    # RPM specification
│       ├── postinstall.sh        # Post-installation script
│       └── preuninstall.sh       # Pre-uninstallation script
├── tests/                        # Unit tests
├── linux_diagnostics.service    # Systemd service file
├── Makefile                      # Build automation
├── pyproject.toml               # Python project configuration
├── monitor.py                   # System resource monitoring script
├── disk_monitor.py              # Disk usage monitoring script
├── compare.py                   # Performance comparison tool
├── disk_plot.py                 # Disk usage visualization
└── README.md                    # This file
```

## 🚀 Quick Start

### Installation

#### From Packages (Recommended)

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

# Install dependencies
pip3 install -r requirements.txt

# Configure (edit config/config.yaml as needed)
sudo mkdir -p /var/log/aod
sudo mkdir -p /var/run/linux_diagnostics

# Copy files to system locations
sudo cp src/* /usr/bin/
sudo cp config/config.yaml /etc/linux_diagnostics/
sudo cp linux_diagnostics.service /etc/systemd/system/

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable linux_diagnostics.service
sudo systemctl start linux_diagnostics.service
```

### Basic Usage

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

## 📊 Monitoring & Analysis Tools

The AODv2 system includes several standalone tools for performance monitoring and data analysis:

### System Resource Monitoring

**monitor.py** - Real-time system resource monitoring
```bash
# Monitor system resources (CPU, memory, disk I/O)
python3 monitor.py [duration_seconds] [interval_seconds]

# Examples
python3 monitor.py 300 1      # Monitor for 5 minutes, 1-second intervals
python3 monitor.py 60         # Monitor for 1 minute, default interval
```

**disk_monitor.py** - Disk usage monitoring and plotting
```bash
# Monitor disk usage with visual output
python3 disk_monitor.py [duration_seconds] [device_path]

# Examples  
python3 disk_monitor.py 300 /dev/sda    # Monitor /dev/sda for 5 minutes
python3 disk_monitor.py 120             # Monitor default device for 2 minutes
```

### Performance Comparison and Analysis

**csv_range_compare.py** - Advanced range-based CSV comparison
```bash
# Compare two CSV files with range-based analysis (0-200s, 200-500s, 500-600s)
python3 csv_range_compare.py file1.csv file2.csv [column_name]

# Examples
python3 csv_range_compare.py baseline.csv test.csv                    # Analyze both CPU and Memory
python3 csv_range_compare.py without_aod.csv with_aod.csv CPU_Percent # Analyze specific column
python3 csv_range_compare.py data1.csv data2.csv Memory_Percent       # Memory-specific analysis
```

Features:
- **Automatic column detection**: Finds CPU and Memory columns automatically
- **Range-based analysis**: Separate statistics for different time periods
- **Visual comparisons**: Generates detailed plots for each range
- **Comprehensive metrics**: Average, max, min, standard deviation, and percentage changes
- **Flexible input**: Supports various timestamp formats and column naming

**compare.py** - Basic CSV comparison and visualization
```bash
# Compare two monitoring CSV files
python3 compare.py file1.csv file2.csv

# Generates comparison graphs and statistics
```

**disk_plot.py** - Disk usage trend visualization
```bash
# Create disk usage plots from monitoring data
python3 disk_plot.py monitoring_data.csv
```

### Sample Data Generation

**generate_sample_csvs.py** - Create test data for analysis
```bash
# Generate sample CSV files for testing comparison tools
python3 generate_sample_csvs.py

# Creates baseline_sample.csv and test_sample.csv with realistic performance data
```

### Tool Dependencies

Install required Python packages:
```bash
pip3 install -r requirements.txt

# Or install individually:
pip3 install pandas matplotlib numpy zstandard PyYAML
```

### Performance Optimizations

- **Zstd Compression**: AODv2 uses Zstandard compression for log archives, providing faster compression and decompression compared to gzip while maintaining excellent compression ratios
- **Range-based Analysis**: The comparison tools support time-range analysis to identify performance changes during specific periods
- **Memory Efficient**: All monitoring tools use streaming data processing to handle large datasets

## ⚙️ Configuration

The main configuration file is located at `config/config.yaml`. Key sections include:

### Basic Settings
```yaml
watch_interval_sec: 1          # Monitoring frequency
aod_output_dir: /var/log/aod   # Output directory for logs
```

### Anomaly Detection
```yaml
guardian:
  anomalies:
    latency:
      type: "Latency"
      tool: "smbslower"
      acceptable_count: 10        # Anomaly threshold
      default_threshold_ms: 10    # Default latency threshold
      track_commands:             # Commands to monitor
        - command: SMB2_READ
          threshold: 8            # Custom threshold in ms
        - command: SMB2_WRITE
          threshold: 12
    
    error:
      type: "Error"
      tool: "smbiosnoop"
      acceptable_count: 10        # Error rate threshold
      track_codes:                # Error codes to monitor
        - EACCES
        - EIO
```

### Cleanup Settings
```yaml
cleanup:
  cleanup_interval_sec: 60       # Cleanup check frequency (default: 60 seconds)
  max_log_age_days: 2           # Maximum log retention (default: 2 days)
  max_total_log_size_mb: 200    # Maximum total log size (default: 200 MB)
  aod_output_dir: /var/log/aod  # Output directory for log storage
```

**SpaceWatcher Behavior**:
- **Normal Operation**: Checks every `cleanup_interval_sec` seconds
- **Size Trigger**: Cleanup when usage exceeds 90% of `max_total_log_size_mb`
- **Emergency Mode**: More aggressive cleanup (80% threshold) when usage exceeds 95%
- **Age Cleanup**: Removes logs older than `max_log_age_days` days
- **Emergency Frequency**: Checks 4x more frequently during emergency conditions
- **File Types**: Only counts completed `.tar.zst` files (prevents race conditions)

### Diagnostic Actions
```yaml
watcher:
  actions:                      # Available diagnostic actions
    - dmesg                     # Kernel messages
    - journalctl                # System journal
    - debugdata                 # Debug information
    - stats                     # CIFS statistics
    - mounts                    # Mount information
    - smbinfo                   # SMB connection details
    - syslogs                   # System logs
```

## 🔧 Performance Monitoring Tools

The repository includes standalone monitoring tools for performance analysis:

### System Resource Monitor (`monitor.py`)

Monitor CPU and memory usage over time:

```bash
# Monitor for 5 minutes (default)
python3 monitor.py

# Monitor for 10 minutes with 2-second intervals
python3 monitor.py 2 10

# Monitor for 30 minutes with 5-second intervals  
python3 monitor.py 5 30
```

**Output:** `system_usage_YYYYMMDD_HHMMSS.csv`

### Disk Usage Monitor (`disk_monitor.py`)

Monitor AOD log directory growth:

```bash
# Monitor every 5 seconds indefinitely
python3 disk_monitor.py

# Monitor every 10 seconds for 30 minutes
python3 disk_monitor.py 10 30

# Quick 5-minute test
python3 disk_monitor.py 2 5
```

**Output:** `disk_usage_YYYYMMDD_HHMMSS.csv`

### Performance Comparison (`compare.py`)

Generate side-by-side performance comparisons:

```bash
# Compare two system monitoring runs
python3 compare.py system_usage_baseline.csv system_usage_with_aod.csv

# Compare CPU and memory usage patterns
python3 compare.py run1.csv run2.csv
```

**Output:** `comparison_graph.png` with statistics

### Disk Usage Visualization (`disk_plot.py`)

Visualize disk usage growth over time:

```bash
# Plot single monitoring session
python3 disk_plot.py disk_usage_20241224_120000.csv

# Compare disk usage between two sessions
python3 disk_plot.py disk_baseline.csv disk_with_aod.csv
```

**Output:** `disk_usage_plot.png` or `disk_usage_comparison.png`

## 📊 Performance Testing Workflow

### Complete AOD Impact Analysis

```bash
# 1. Baseline measurement (without AOD)
sudo systemctl stop linux_diagnostics.service
python3 monitor.py 10 10  # 10s intervals, 10 minutes
# Save as: baseline_cpu.csv

# 2. With AOD monitoring  
sudo systemctl start linux_diagnostics.service
python3 disk_monitor.py 5 15  # Monitor disk growth
python3 monitor.py 10 10      # Monitor CPU/memory
# Save as: with_aod_disk.csv, with_aod_cpu.csv

# 3. Post-AOD measurement
sudo systemctl stop linux_diagnostics.service  
python3 monitor.py 10 10      # Final measurement
# Save as: post_aod_cpu.csv

# 4. Generate comparison reports
python3 compare.py baseline_cpu.csv with_aod_cpu.csv
python3 disk_plot.py with_aod_disk.csv
```

### Automated Testing Script

Use the provided `run_experiment.sh` script for automated testing:

```bash
# Make script executable
chmod +x run_experiment.sh

# Run automated experiment with custom workload
./run_experiment.sh -w "stress --cpu 4 --timeout 600s" -d 10 -k 15

# Run with file operations workload
./run_experiment.sh -w "find /var/log -name '*.log' | xargs grep -i error" -d 5
```

The script automatically:
- Runs baseline measurements without AOD
- Starts AOD and measures impact
- Stops AOD and measures recovery
- Generates comparison graphs and statistics
- Creates comprehensive reports

## 🔍 Monitoring and Troubleshooting

### Log Locations

- **Service Logs:** `journalctl -u linux_diagnostics.service`
- **AOD Output:** `/var/log/aod/batches/`
- **Diagnostic Data:** `/var/log/aod/batches/aod_TIMESTAMP/`

### Common Issues

**Permission Errors:**
```bash
# Ensure proper permissions
sudo chown -R root:root /var/log/aod
sudo chmod 755 /var/log/aod
```

**Service Won't Start:**
```bash
# Check configuration
sudo python3 -c "import yaml; yaml.safe_load(open('/etc/linux_diagnostics/config.yaml'))"

# Check dependencies
sudo python3 -c "import numpy, yaml"
```

**High Disk Usage:**
```bash
# Check current disk usage
du -sh /var/log/aod/batches/

# Manual cleanup if needed
sudo systemctl stop linux_diagnostics.service
sudo rm -rf /var/log/aod/batches/aod_*
sudo systemctl start linux_diagnostics.service
```

### Performance Metrics

Monitor AOD's own performance impact:

```bash
# CPU usage by AOD processes
ps aux | grep linux_diagnostics

# Memory usage
sudo systemctl status linux_diagnostics.service

# Disk I/O impact
sudo iotop -a -o -d 1

# Network impact (if using remote logging)
sudo nethogs
```

## 🧪 Testing

Run the test suite:

```bash
# Run all tests
python3 -m pytest tests/

# Run specific test modules
python3 -m pytest tests/test_controller.py -v

# Run with coverage
python3 -m pytest tests/ --cov=src --cov-report=html
```

### Test Categories

- **Unit Tests:** Individual component testing
- **Integration Tests:** Cross-component functionality
- **Performance Tests:** Resource usage validation
- **Configuration Tests:** Config validation and edge cases

## 📦 Building Packages

### Prerequisites

**Debian/Ubuntu:**
```bash
sudo apt-get install build-essential devscripts debhelper
```

**RHEL/CentOS/Fedora:**
```bash
sudo yum install rpm-build rpmlint
# or
sudo dnf install rpm-build rpmlint
```

### Build Commands

```bash
# Build both packages
make all

# Build only DEB package
make debian

# Build only RPM package  
make rpm

# Clean build artifacts
make clean
```

### Package Contents

Both packages include:
- Service binary and modules
- Configuration files
- Systemd service file
- eBPF monitoring tools
- Documentation
- Log directories

## 🔧 Development

### Code Style

The project uses Black for code formatting:

```bash
# Format code
black src/ tests/ *.py

# Check formatting
black --check src/ tests/ *.py
```

### Adding New Anomaly Handlers

1. Create handler in `src/handlers/`:
```python
from base.AnomalyHandlerBase import AnomalyHandler

class MyAnomalyHandler(AnomalyHandler):
    def detect(self, events_batch):
        # Implementation here
        return anomaly_detected
```

2. Register in `AnomalyWatcher.py`:
```python
ANOMALY_HANDLER_REGISTRY = {
    AnomalyType.MY_TYPE: MyAnomalyHandler,
    # ...
}
```

3. Add configuration schema to `config_schema.py`

### Adding New Quick Actions

1. Create action in `src/handlers/`:
```python
from base.QuickAction import QuickAction

class MyQuickAction(QuickAction):
    def collect(self):
        # Implementation here
        return collected_data
```

2. Register in `EventDispatcher.py`

## 📋 System Requirements

### Minimum Requirements

- **OS:** Linux kernel 4.18+ (for eBPF support)
- **Python:** 3.8+
- **Memory:** 512MB RAM
- **Storage:** 1GB free space for logs
- **Privileges:** Root access for system monitoring

### Dependencies

The Controller and its components require only these Python packages:

**Core Dependencies:**
- `numpy` - Used by anomaly handlers for efficient event processing
- `PyYAML` - Configuration file parsing (ConfigManager)
- `zstandard` - Fast compression library for log archives (replaces gzip for better performance)

**Standard Library Modules Used:**
- `threading`, `queue` - Concurrency and communication
- `subprocess`, `os`, `signal` - System interaction
- `logging` - Logging infrastructure  
- `time`, `pathlib` - Basic utilities
- `ctypes` - Low-level system calls
- `asyncio`, `tarfile` - Async operations and file handling

**System Tools Required:**
- `systemctl` - Service management
- `journalctl` - System journal access
- eBPF tools (provided in `src/bin/`)

### Installation

```bash
# Install core dependencies
pip3 install numpy PyYAML zstandard

# Or using requirements.txt
pip3 install -r requirements.txt

# Or using system package manager  
sudo apt-get install python3-numpy python3-yaml  # Debian/Ubuntu (zstandard via pip)
sudo yum install python3-numpy python3-PyYAML   # RHEL/CentOS (zstandard via pip)
```

**Note:** The performance monitoring tools (`monitor.py`, `compare.py`, etc.) require additional packages (`pandas`, `matplotlib`) but are not needed for the core Controller functionality.