# Advanced Usage and Developer Guide

This document provides advanced guidance for developers and power users, including details on monitoring, testing, and extending the AOD system. For installation and basic configuration, please see the main [README.md](README.md).

## 📊 Monitoring & Analysis Tools

The AODv2 system includes several standalone tools for performance monitoring and data analysis.

### Tool Dependencies

Install required Python packages:
```bash
# Install all tool dependencies
pip3 install pandas matplotlib numpy zstandard PyYAML
```

### System Resource Monitoring (`monitor.py`)

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

### Performance Comparison (`compare.py` and `csv_range_compare.py`)

**`compare.py` (Basic):**
Generate side-by-side performance comparisons:
```bash
# Compare two system monitoring runs
python3 compare.py system_usage_baseline.csv system_usage_with_aod.csv
```
**Output:** `comparison_graph.png` with statistics

**`csv_range_compare.py` (Advanced):**
Compare two CSV files with range-based analysis (0-200s, 200-500s, 500-600s).
```bash
# Analyze both CPU and Memory
python3 csv_range_compare.py baseline.csv test.csv
# Analyze specific column
python3 csv_range_compare.py without_aod.csv with_aod.csv CPU_Percent
```
Features:
- **Automatic column detection**: Finds CPU and Memory columns automatically
- **Range-based analysis**: Separate statistics for different time periods
- **Visual comparisons**: Generates detailed plots for each range
- **Comprehensive metrics**: Average, max, min, standard deviation, and percentage changes
- **Flexible input**: Supports various timestamp formats and column naming

### Disk Usage Visualization (`disk_plot.py`)

Visualize disk usage growth over time:

```bash
# Plot single monitoring session
python3 disk_plot.py disk_usage_20241224_120000.csv

# Compare disk usage between two sessions
python3 disk_plot.py disk_baseline.csv disk_with_aod.csv
```

**Output:** `disk_usage_plot.png` or `disk_usage_comparison.png`

### Sample Data Generation (`generate_sample_csvs.py`)

Create test data for analysis tools:
```bash
# Generate sample CSV files for testing comparison tools
python3 generate_sample_csvs.py
```
**Output:** `baseline_sample.csv` and `test_sample.csv` with realistic performance data.

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

## 🧪 Testing the System

A robust testing strategy is essential for maintaining the quality and reliability of AOD.

### Unit Tests

The project uses `pytest` for unit testing individual components.

```bash
# Install testing dependencies
pip3 install pytest

# Run all unit tests
pytest tests/
```

### Integration Tests

**Currently, the project lacks a dedicated integration testing suite.** This is a critical area for future improvement.

Integration tests would verify that the components work together as expected in a realistic environment. A typical test case would involve:
1.  Starting the `linux_diagnostics` service.
2.  Using a workload to trigger a specific anomaly (e.g., high latency).
3.  Asserting that the `AnomalyWatcher` correctly detects the anomaly.
4.  Verifying that the `EventDispatcher` triggers the configured `QuickActions`.
5.  Checking the output directory to ensure the correct diagnostic files were created and have the expected content.

### Code Coverage

To measure how much of the codebase is covered by unit tests, you can use the `pytest-cov` plugin.

```bash
# Install coverage tool
pip3 install pytest-cov

# Run tests and generate a coverage report
pytest --cov=src tests/
```

## 🔧 Extending AOD

The AOD system is designed to be extensible. You can add new anomaly detectors and diagnostic actions to tailor it to your specific needs.

### Adding a New Anomaly Type

Let's walk through the process using the `error` anomaly and `smbiosnoop` eBPF tool as a concrete example.

**Step 1: Add the eBPF Tool**
First, you need the eBPF tool that will produce the data. For this example, assume you have a compiled `smbiosnoop` tool that traces SMB error codes and prints them to standard output. 
You would place this tool in a directory like `/usr/local/bin/` so the AOD service can execute it.

**Step 2: Add code to execute the eBPF Tool in the Controller**

1. Add the `"tool_name": self._get_toolname_cmd` in `self.tool_cmd_builders` in `__init__`
```python
#src/Controller.py

# ... existing code ...

    def __init__(self, config_path: str):

        # ... existing code ...

        self.tool_cmd_builders = {
            "smbslower": self._get_smbsloweraod_cmd,
            "smbiosnoop": self._get_smbiosnoop_cmd,
        }

        # ... existing code ...

# ... existing code ...

```

2. add a `_get_toolname_cmd` function
calculate whichever params you want, 
find the path to the ebpf binary you want to execute (look at the example)
and return the command array
```python
#src/Controller.py

# ... existing code ...

def _get_smbiosnoop_cmd(self) -> list[str]:

        #calculate whichever params you want
        
        ebpf_binary_path = os.path.join(os.path.dirname(__file__), "bin", "smbiosnoop")
        return [ebpf_binary_path, params]   # return the ebpf command you want to run (params not necessary)

# ... existing code ...

```

**Step 3: Create the Anomaly Handler**
Create a new Python file in `src/handlers/`, for example, `error_anomaly_handler.py`.
```python
# src/handlers/error_anomaly_handler.py

import numpy as np
from base.AnomalyHandlerBase import AnomalyHandler

class LatencyAnomalyHandler(AnomalyHandler):

        def __init__(self, error_config):
                super().__init__(error_config)
                # add anything else you want to initialize

        def detect(self, events_batch: np.ndarray) -> bool:
                # add logic to analyze the events_batch and return true if an anomaly is detected, else false
```

**Step 4: Register the New Handler**
In `src/AnomalyWatcher.py`, import and register your new handler type so the `AnomalyWatcher` knows about it.

```python
# src/AnomalyWatcher.py

# ... other imports
from handlers.latency_anomaly_handler import LatencyAnomalyHandler
from handlers.error_anomaly_handler import ErrorAnomalyHandler # <-- Add this import

# ... existing code ...
        self.anomaly_handlers = {
            "Latency": LatencyAnomalyHandler,
            "Error": ErrorAnomalyHandler, # <-- Add this line
        }
# ... existing code ...
```


**Step 5: Update `config.yaml`**
Finally, add the configuration for your new anomaly to `config/config.yaml`.
Follow the config schema specified in `src/utils/config_schema.py`

```yaml
# config/config.yaml
guardian:
  anomalies:
    latency:
      # ... latency config ...
    error:
      type: "Error"
      tool: "/usr/local/bin/smbiosnoop" # Path to your eBPF tool
      mode: "trackonly"
      acceptable_count: 10
      track_codes:
        - "EACCES"
        - "EAGAIN"
        - "EIO"
      actions:
        - dmesg
        - journalctl
```

**Step 6: Update `ConfigManager.py`**

```python
#src/ConfigManager.py

# ... existing code ...

        def _get_track_for_anomaly(self, anomaly: dict):
                
                # ... existing code ...

                dispatch = {
                    AnomalyType.LATENCY: self._get_latency_track_cmds,
                    AnomalyType.ERROR: self._get_error_track_cmds, # <-- Add this line
                    # Add more types here as needed
                }
        
                # ... existing code ...

        def _get_error_track_cmds(self, anomaly):
                # Add logic to get the track cmds you want 
                # return the track cmds

# ... existing code ...

```



### Adding a New Quick Action

Quick Actions are simple, standalone diagnostic commands that are triggered when any anomaly is detected.

**Step 1: Create the Quick Action Class**
Create a new file `ToolQuickAction.py` in `src/handlers/`, for example, `LsofQuickAction.py`.

**Step 2: Implement the `get_command` Method**
The class must inherit from `QuickAction` and implement the get_command method. 
In the `__init__`, specify the name of the log file you want as shown in the example.
Initialize any params if u want.
get_command shld return a list consisting of the following: array of the cmd u want to implement, "cmd"/"cat"
cmd ->  need a seperate process to implement this task.
cat ->  simple cat operation
For example, to capture the output of network connections using `lsof`:

```python
# src/handlers/LsofQuickAction.py
import subprocess
from pathlib import Path
from base.QuickAction import QuickAction

class LsofQuickAction(QuickAction):
    def __init__(self, batches_root: str, params):
        """Args:
            batches_root (str): Root directory for log batches.
            params: You can add any params if you want
        """
        super().__init__(batches_root, "lsof.log")   # lsof.log is the name of the log file
        # can add any self.params if u want

    def get_command(self) -> list:
        return ["lsof","-i"], "cmd"
        # return array of cmd u want to run , whether it is a cmd or cat 
        
        

```

**Step 3: Add Quick Action in the Log Collector**
Import the ToolQuickAction you created from the handlers class
eg. Import the LsofQuickAction from handlers.LsofQuickAction.
In the Log Collector's `__init__`, update the `self.action_factory` add `"toolname": lambda: ToolQuickAction()


```python
#src/LogCollector.py

# ... existing code ...
from handlers.LsofQuickAction import LsofQuickAction
# ... existing code ...

class LogCollector:
    def __init__(self, controller):
        # ... existing code ...
        self.action_factory = {
            "journalctl": lambda: JournalctlQuickAction(self.aod_output_dir, self.anomaly_interval),
            "stats": lambda: CifsstatsQuickAction(self.aod_output_dir),
            "debugdata": lambda: DebugDataQuickAction(self.aod_output_dir),
            "dmesg": lambda: DmesgQuickAction(self.aod_output_dir, self.anomaly_interval),
            "mounts": lambda: MountsQuickAction(self.aod_output_dir),
            "smbinfo": lambda: SmbinfoQuickAction(self.aod_output_dir),
            "syslogs": lambda: SysLogsQuickAction(self.aod_output_dir, num_lines=100),
        }
        # ... existing code ...

# ... existing code ...



**Step 4: Update `config.yaml`**
Add the name of your new action to the `watcher: actions:` list in `config/config.yaml`. The name must match the toolname you gave in the previous step.

```yaml
# config/config.yaml
watcher:
  actions:
    - dmesg
    - journalctl
    - lsof  # <-- Add your new action here
```
