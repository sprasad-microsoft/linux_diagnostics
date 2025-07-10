# Configuration Guide

This guide provides comprehensive documentation for configuring AODv2 (Linux Diagnostics Controller) to meet your specific monitoring and diagnostic needs.

## 📋 Configuration Overview

AODv2 uses a YAML-based configuration system that allows fine-grained control over:
- Monitoring intervals and thresholds
- Anomaly detection parameters
- Diagnostic collection actions
- Cleanup and maintenance settings
- Audit and logging configuration

## 📄 Configuration File Structure

### Default Configuration Location
```bash
config/config.yaml  # Relative to project root
```

**Note:** The configuration file path is relative to the source directory. In production deployments, this may be configured differently based on your installation method.

### Complete Configuration Example
```yaml
# Global monitoring settings
watch_interval_sec: 1
aod_output_dir: /var/log/aod

# Watcher configuration
watcher:
  actions:
    - dmesg
    - journalctl
    - debugdata
    - stats
    - mounts
    - smbinfo
    - syslogs

guardian:
  anomalies:
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

    latency:
      type: "Latency"
      tool: "smbslower"
      mode: "all"
      acceptable_count: 10
      default_threshold_ms: 20
      track_commands:
        - command: SMB2_WRITE
          threshold: 50
        - command: SMB2_READ
          threshold: 30
      actions:
        - dmesg
        - journalctl
        - debugdata
        - stats
        - mounts
        - smbinfo
        - syslogs

# Cleanup configuration
cleanup:
  cleanup_interval_sec: 60
  max_log_age_days: 2
  max_total_log_size_mb: 0.5

# Audit configuration
audit:
  enabled: true
```

## 🔧 Configuration Sections

### 1. Global Settings

#### `watch_interval_sec`
**Type:** Integer  
**Default:** 1  
**Description:** Interval in seconds for batch processing of events by AnomalyWatcher.

```yaml
watch_interval_sec: 1  # Process events every second
```

**Performance Impact:**
- Lower values: More responsive detection, higher CPU usage
- Higher values: Less responsive detection, lower CPU usage

#### `aod_output_dir`
**Type:** String  
**Default:** `/var/log/aod`  
**Description:** Directory where diagnostic logs are stored.

```yaml
aod_output_dir: /var/log/aod
```

**Requirements:**
- Directory must be writable by the service user
- Should have sufficient disk space for log storage
- Consider using a dedicated partition for large-scale deployments

### 2. Watcher Configuration

#### `watcher.actions`
**Type:** List of Strings  
**Description:** Available QuickActions that can be executed during diagnostic collection.

```yaml
watcher:
  actions:
    - dmesg        # Kernel messages
    - journalctl   # Systemd journal
    - debugdata    # SMB debug information
    - stats        # CIFS statistics
    - mounts       # Mount information
    - smbinfo      # SMB connection details
    - syslogs      # System logs
```

**Available Actions:**
- `dmesg`: Kernel ring buffer messages (last `anomaly_interval` minutes)
- `journalctl`: Systemd journal entries (last `anomaly_interval` minutes)
- `debugdata`: SMB debug data from `/proc/fs/cifs/DebugData`
- `stats`: CIFS statistics from `/proc/fs/cifs/Stats`
- `mounts`: Mount point information from `/proc/mounts`
- `smbinfo`: SMB connection information
- `syslogs`: System log collection (last 100 lines by default)

**Note:** All actions are implemented as QuickAction classes in the `src/handlers/` directory.

#### `guardian.anomalies`
**Type:** Dictionary  
**Description:** Configuration for anomaly detection handlers.

### 3. Anomaly Configuration

#### Error Anomaly Handler
**Status:** Placeholder implementation - not yet functional.

Detects patterns of error responses that exceed configured thresholds.

```yaml
guardian:
  anomalies:
    error:
      type: "Error"
      tool: "smbiosnoop"  # Planned tool - not yet implemented
      mode: "trackonly"
      acceptable_count: 10
      track_codes:
        - EACCES
        - EAGAIN
        - EIO
      actions:
        - dmesg
        - journalctl
```

**Note:** This handler is currently a placeholder and will return `false` for all events. The error detection logic and corresponding eBPF tools are planned for future implementation.

**Configuration Parameters:**

##### `type`
**Type:** String  
**Values:** "Error"  
**Description:** Identifies this as an error anomaly handler.

##### `tool`
**Type:** String  
**Values:** "smbiosnoop" (planned - not yet implemented)  
**Description:** eBPF tool used for data collection. Currently not functional.

##### `mode`
**Type:** String  
**Required:** Yes  
**Values:** "all", "trackonly", "excludeonly"  
**Description:** Determines which error codes to monitor.

- `all`: Monitor all error codes
- `trackonly`: Monitor only specified error codes in `track_codes`
- `excludeonly`: Monitor all except specified error codes in `exclude_codes`

##### `acceptable_count`
**Type:** Integer  
**Required:** Yes  
**Description:** Maximum number of errors allowed within the watch interval before triggering an anomaly.

##### `track_codes`
**Type:** List of Strings  
**Description:** Error codes to track (used with `trackonly` mode).

**Common Error Codes:**
- `EACCES`: Permission denied
- `EAGAIN`: Resource temporarily unavailable
- `EIO`: Input/output error
- `ENOENT`: No such file or directory
- `ENOSPC`: No space left on device
- `ETIMEDOUT`: Connection timed out

##### `exclude_codes`
**Type:** List of Strings  
**Description:** Error codes to exclude (used with `excludeonly` mode).

```yaml
# Alternative configuration using excludeonly mode
guardian:
  anomalies:
    error:
  type: "Error"
  tool: "smbiosnoop"
  mode: "excludeonly"
  acceptable_count: 5
  exclude_codes:
    - ENOENT  # Don't track "file not found" errors
  actions:
    - dmesg
    - journalctl
```

#### Latency Anomaly Handler
Detects latency spikes that exceed configured thresholds.

```yaml
guardian:
  anomalies:
    latency:
    type: "Latency"
    tool: "smbslower"
    mode: "all"
    acceptable_count: 10
    default_threshold_ms: 20
    track_commands:
      - command: SMB2_WRITE
        threshold: 50
      - command: SMB2_READ
        threshold: 30
    actions:
      - dmesg
      - journalctl
      - debugdata
      - stats
      - mounts
      - smbinfo
      - syslogs
```

**Configuration Parameters:**

##### `type`
**Type:** String  
**Values:** "Latency"  
**Description:** Identifies this as a latency anomaly handler.

##### `tool`
**Type:** String  
**Values:** "smbslower"  
**Description:** eBPF tool used for latency monitoring.

**Available Tools:**
- `smbslower`: Monitors SMB operation latency (implemented in `src/bin/smbsloweraod`)

##### `mode`
**Type:** String  
**Required:** Yes  
**Values:** "all", "trackonly", "excludeonly"  
**Description:** Determines which commands to monitor.

##### `acceptable_count`
**Type:** Integer  
**Required:** Yes  
**Description:** Maximum number of latency violations allowed within the watch interval.

##### `default_threshold_ms`
**Type:** Integer  
**Default:** 10  
**Description:** Default latency threshold in milliseconds for commands not specifically configured.

##### `track_commands`
**Type:** List of Objects  
**Description:** Command-specific threshold configuration.

**Command Configuration:**
```yaml
track_commands:
  - command: SMB2_WRITE
    threshold: 50        # milliseconds
  - command: SMB2_READ
    threshold: 30        # milliseconds
  - command: SMB2_CREATE # it is not compulsory to specify threshold for all commands
```

**Available SMB Commands:**
- `SMB2_READ`: File read operations
- `SMB2_WRITE`: File write operations
- `SMB2_CREATE`: File/directory creation
- `SMB2_CLOSE`: File close operations
- `SMB2_FLUSH`: File flush operations
- `SMB2_QUERY_INFO`: File information queries
- `SMB2_SET_INFO`: File information updates
- `SMB2_QUERY_DIRECTORY`: Directory listing operations

### 4. Cleanup Configuration

#### `cleanup.cleanup_interval_sec`
**Type:** Integer  
**Default:** 60  
**Description:** Interval in seconds between cleanup operations.

```yaml
cleanup:
  cleanup_interval_sec: 60  # Run cleanup every minute
```

#### `cleanup.max_log_age_days`
**Type:** Integer  
**Default:** 2  
**Description:** Maximum age of log files in days before they are removed.

```yaml
cleanup:
  max_log_age_days: 2  # Remove logs older than 2 days
```

#### `cleanup.max_total_log_size_mb`
**Type:** Float  
**Default:** 0.5  
**Description:** Maximum total size of all log files in megabytes.

```yaml
cleanup:
  max_total_log_size_mb: 0.5  # Keep total logs under 512KB
```

### 5. Audit Configuration

#### `audit.enabled`
**Type:** Boolean  
**Default:** true  
**Description:** Enables audit logging for all system operations.

```yaml
audit:
  enabled: true
```

**Audit Features:**
- Operation logging to syslog
- Configuration change tracking
- Anomaly detection events
- Diagnostic collection records

## 🎯 Configuration Examples

### High-Performance Environment
Optimized for high-traffic SMB workloads:

```yaml
watch_interval_sec: 0.5  # More responsive detection
aod_output_dir: /var/log/aod

watcher:
  actions:
    - dmesg
    - journalctl
    - debugdata
    - stats

guardian:
  anomalies:
    latency:
      type: "Latency"
      tool: "smbslower"
      mode: "all"
      acceptable_count: 25     # Higher threshold for busy systems
      default_threshold_ms: 50  # Higher latency tolerance
      track_commands:
        - command: SMB2_WRITE
          threshold: 100
        - command: SMB2_READ
          threshold: 75
      actions:
        - debugdata
        - stats

cleanup:
  cleanup_interval_sec: 30    # More frequent cleanup
  max_log_age_days: 1         # Shorter retention
  max_total_log_size_mb: 100  # Larger log capacity

audit:
  enabled: true
```

### Development Environment
Optimized for development and testing:

```yaml
watch_interval_sec: 2        # Less aggressive monitoring
aod_output_dir: /tmp/aod_logs

watcher:
  actions:
    - dmesg
    - journalctl

guardian:
  anomalies:
    error:
      type: "Error"
      tool: "smbiosnoop"
      mode: "trackonly"
      acceptable_count: 5      # Lower threshold for testing
      track_codes:
        - EACCES
        - EIO
      actions:
        - dmesg

    latency:
      type: "Latency"
      tool: "smbslower"
      mode: "all"
      acceptable_count: 5      # Lower threshold for testing
      default_threshold_ms: 10  # Stricter latency detection
      actions:
        - dmesg
        - journalctl

cleanup:
  cleanup_interval_sec: 300   # Less frequent cleanup
  max_log_age_days: 0.5       # 12 hours retention
  max_total_log_size_mb: 10   # Small log capacity

audit:
  enabled: true
```

### Minimal Resource Environment
Optimized for resource-constrained systems:

```yaml
watch_interval_sec: 5        # Reduced monitoring frequency
aod_output_dir: /var/log/aod

watcher:
  actions:
    - dmesg     # Only essential actions

guardian:
  anomalies:
    error:
      type: "Error"
      tool: "smbiosnoop"
      mode: "trackonly"
      acceptable_count: 20     # Higher threshold
      track_codes:
        - EACCES
        - EIO
      actions:
        - dmesg

cleanup:
  cleanup_interval_sec: 600   # 10-minute cleanup intervals
  max_log_age_days: 0.25      # 6 hours retention
  max_total_log_size_mb: 1    # Minimal log capacity

audit:
  enabled: false              # Disable audit to save resources
```

## 🔍 Configuration Validation

### Default Values
When not specified in the configuration, the following default values are used:

**Latency Anomaly Handler:**
- `mode`: "all" (if not specified)
- `default_threshold_ms`: 10 (if not specified)
- `track_commands`: [] (empty list if not specified)
- `exclude_commands`: [] (empty list if not specified)
- `actions`: [] (empty list if not specified)

**Error Anomaly Handler:**
- `mode`: "all" (if not specified)  
- `track_codes`: [] (empty list if not specified)
- `exclude_codes`: [] (empty list if not specified)
- `actions`: [] (empty list if not specified)

**Note:** All other fields (`type`, `tool`, `acceptable_count`) are required and have no defaults.

### Schema Validation
AODv2 validates configuration against a predefined schema on startup using the `ConfigManager` class:

**Validation Process:**
1. **YAML Syntax Validation**: Ensures valid YAML format
2. **Required Fields Check**: Verifies all required fields are present
3. **Data Type Validation**: Checks field types match expected schema
4. **Value Range Validation**: Ensures values are within acceptable ranges
5. **Cross-Field Validation**: Validates relationships between fields (e.g., mode vs. track_codes)
6. **Command/Code Validation**: Verifies SMB commands and error codes exist in predefined lists
7. **Runtime Action Validation**: Checks action names at runtime (service startup), logs warnings for invalid actions but continues execution

**Validation Errors:**
```python
# Configuration validation errors will be logged with specific details
ValueError: No items to track for anomaly 'error' after applying config logic
ValueError: Code INVALID_CODE not found in track codes
ValueError: Code EACCES is duplicated in track and exclude codes
ValueError: Invalid threshold value in track command: {'command': 'SMB2_WRITE', 'threshold': -1}
UserWarning: Error exclude items will be ignored in trackonly mode

# Runtime warnings for invalid actions (service continues running)
WARNING: No factory for action 'invalid_action' in anomaly 'latency'
WARNING: Unknown anomaly type 'InvalidType' for 'my_anomaly'
```

### Common Configuration Errors

#### 1. Invalid Data Types
```yaml
# Incorrect - string instead of integer
watch_interval_sec: "1"

# Correct
watch_interval_sec: 1
```

#### 2. Missing Required Fields
```yaml
# Incorrect - missing required fields
guardian:
  anomalies:
    error:
      type: "Error"
      # Missing: tool, mode, acceptable_count

# Correct
guardian:
  anomalies:
    error:
      type: "Error"
      tool: "smbiosnoop"
      mode: "trackonly"
      acceptable_count: 10
```

#### 3. Invalid Mode Configuration
```yaml
# Incorrect - using both track_codes and exclude_codes with trackonly mode
guardian:
  anomalies:
    error:
      mode: "trackonly"
      track_codes: ["EACCES"]
      exclude_codes: ["ENOENT"]  # This will be ignored with a warning

# Correct - use only track_codes with trackonly mode
guardian:
  anomalies:
    error:
      mode: "trackonly"
      track_codes: ["EACCES"]
```

#### 4. Invalid Error Codes
```yaml
# Incorrect - invalid error code
guardian:
  anomalies:
    error:
      mode: "trackonly"
      track_codes: ["INVALID_CODE"]  # Not in ALL_ERROR_CODES

# Correct - use valid errno codes
guardian:
  anomalies:
    error:
      mode: "trackonly"
      track_codes: ["EACCES", "EIO"]
```

#### 5. Invalid SMB Commands
```yaml
# Incorrect - invalid SMB command
guardian:
  anomalies:
    latency:
      track_commands:
        - command: "INVALID_CMD"  # Not in ALL_SMB_CMDS
          threshold: 50

# Correct - use valid SMB commands
guardian:
  anomalies:
    latency:
      track_commands:
        - command: "SMB2_WRITE"
          threshold: 50
```

#### 6. Invalid Action Names
```yaml
# Incorrect - action doesn't exist
guardian:
  anomalies:
    latency:
      actions:
        - dmesg
        - invalid_action  # Not in action_factory

# Correct - use valid action names
guardian:
  anomalies:
    latency:
      actions:
        - dmesg
        - journalctl
```

**Valid Action Names:**
- `journalctl`, `stats`, `debugdata`, `dmesg`, `mounts`, `smbinfo`, `syslogs`

**Behavior:** Invalid actions are ignored with a warning log message, but the service continues to run with valid actions.

### Testing Configuration

**Validation Checklist:**
- [ ] YAML syntax is valid
- [ ] All required fields are present (`type`, `tool`, `mode`, `acceptable_count`)
- [ ] SMB commands exist in `ALL_SMB_CMDS`
- [ ] Error codes exist in `ALL_ERROR_CODES` (errno values)
- [ ] Thresholds are positive numbers
- [ ] Mode configuration is consistent with track/exclude lists
- [ ] Action names match available QuickActions
- [ ] No duplicate codes in track/exclude lists

This configuration guide provides the foundation for effectively deploying and tuning AODv2 in various environments, from development systems to high-performance production deployments.
