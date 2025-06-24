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

- **Controller**: The central orchestrator that manages component lifecycle, handles service startup/shutdown, supervises thread execution, and coordinates graceful error recovery. Acts as the main entry point and service manager for the entire system.

- **AnomalyWatcher**: The intelligent detection engine that continuously processes incoming events from eBPF tools. It maintains separate handlers for different anomaly types, applies configurable thresholds, and triggers alerts when patterns indicate performance issues.

- **EventDispatcher**: The routing and coordination hub that receives anomaly notifications and determines appropriate diagnostic responses. It manages the execution pipeline and ensures proper sequencing of diagnostic actions.

- **LogCollector**: The data collection engine responsible for executing diagnostic commands, gathering system information, compressing results, and organizing output into structured batches for analysis.

- **SpaceWatcher**: The autonomous housekeeping service that monitors disk usage, enforces retention policies, and performs automatic cleanup operations to prevent storage exhaustion. Features intelligent size-based and age-based cleanup strategies, efficient space calculation using logical file sizes (matching `tree -h` output), and configurable thresholds with automatic triggering at 90% capacity.

- **ConfigManager**: The configuration management system that handles YAML parsing, validates settings against schemas, and provides runtime configuration access throughout the system.

### Component Communication

The architecture uses a producer-consumer model with thread-safe queues for inter-component communication:

- **Event Queue**: High-throughput queue carrying raw monitoring events from eBPF tools to the AnomalyWatcher
- **Anomaly Queue**: Alert queue transmitting detected anomalies from AnomalyWatcher to EventDispatcher  
- **Action Queue**: Task queue routing diagnostic requests from EventDispatcher to LogCollector

### Thread Management

Each component runs in its own dedicated thread with proper lifecycle management:
- Graceful startup sequencing with dependency resolution
- Coordinated shutdown with cleanup and resource deallocation
- Signal handling for service control and emergency stops
- Thread naming for easy identification in system monitoring tools
- Automatic restart of threads/processes if they stop unexpectedly

## 🔄 Real-Time Processing Pipeline

AODv2's real-time processing system is built around an event streaming architecture.

### Event Collection Layer

**eBPF Monitoring Tools**:
- `smbsloweraod`: Kernel-level SMB command latency monitoring with microsecond precision
- `smbiosnoop`: Real-time SMB I/O and error code tracking  
- Custom eBPF programs for specific monitoring requirements


### Stream Processing

**Event Flow**:
1. **Kernel Events**: eBPF programs capture SMB operations
2. **User Space Transfer**: Events transferred to AODv2 process
3. **Batch Processing**: Events accumulated into batches (configurable interval)
4. **Analysis**: Anomaly handlers process batches
5. **Threshold Evaluation**: Analysis against configurable thresholds
6. **Alert Generation**: Anomaly notifications generated for threshold violations

**Processing Characteristics**:
- **No Event Loss**: Ring buffer to AnomalyWatcher no packet lost, all analyzed
- **Event Processing**: Configurable batch intervals
- **Fault Tolerance**: Processing continues despite individual event errors

### Anomaly Detection Algorithms

**Latency Detection**:
- Per-command threshold evaluation (SMB2_READ, SMB2_WRITE, etc.)
- Configurable acceptable violation counts within time windows
- Emergency detection for operations exceeding 1-second thresholds

**Error Pattern Detection**:
- Error code frequency analysis with configurable tracking lists

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
pip3 install numpy PyYAML

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
  cleanup_interval_sec: 60       # Cleanup frequency
  max_log_age_days: 2           # Maximum log retention
  max_total_log_size_mb: 200    # Maximum total log size
```

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
pip3 install numpy PyYAML

# Or using system package manager
sudo apt-get install python3-numpy python3-yaml  # Debian/Ubuntu
sudo yum install python3-numpy python3-PyYAML   # RHEL/CentOS
```

**Note:** The performance monitoring tools (`monitor.py`, `compare.py`, etc.) require additional packages (`psutil`, `pandas`, `matplotlib`) but are not needed for the core Controller functionality.