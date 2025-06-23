#!/bin/bash
# Comprehensive profiling script for multi-process Python + eBPF + subprocess system

# Enable strict error handling
set -e  # Exit on any error
set -u  # Exit on undefined variables
set -o pipefail  # Exit on pipe failures

# Configuration
DURATION=${1:-30}   #default duration is 30 seconds
OUTPUT_DIR="profiling_outputs/full_system_profile_$(date +%Y%m%d_%H%M%S)"
CONTROLLER_PID=""
PYTHON_CONTROLLER_PID=""
SMBSLOWER_PID=""

# Error tracking
ERROR_LOG=""
ERRORS_ENCOUNTERED=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Error handling functions
log_error() {
    local function_name="$1"
    local command="$2"
    local error_code="$3"
    local error_msg="$4"
    
    ERRORS_ENCOUNTERED=$((ERRORS_ENCOUNTERED + 1))
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local error_entry="[$timestamp] ERROR in $function_name: Command '$command' failed with exit code $error_code: $error_msg"
    
    echo -e "${RED}$error_entry${NC}" >&2
    ERROR_LOG="$ERROR_LOG\n$error_entry"
    echo "$error_entry" >> "$OUTPUT_DIR/error_log.txt"
}

log_warning() {
    local function_name="$1"
    local message="$2"
    
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local warning_entry="[$timestamp] WARNING in $function_name: $message"
    
    echo -e "${YELLOW}$warning_entry${NC}" >&2
    echo "$warning_entry" >> "$OUTPUT_DIR/error_log.txt"
}

log_info() {
    local function_name="$1"
    local message="$2"
    
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${BLUE}[$timestamp] INFO ($function_name): $message${NC}"
    echo "[$timestamp] INFO ($function_name): $message" >> "$OUTPUT_DIR/debug_log.txt"
}

# Safe command execution with error handling
safe_exec() {
    local function_name="$1"
    local description="$2"
    shift 2
    local command="$@"
    
    log_info "$function_name" "Executing: $description"
    log_info "$function_name" "Command: $command"
    
    if eval "$command"; then
        log_info "$function_name" "SUCCESS: $description"
        return 0
    else
        local exit_code=$?
        log_error "$function_name" "$command" "$exit_code" "$description failed"
        return $exit_code
    fi
}

# Safe background execution
safe_background_exec() {
    local function_name="$1"
    local description="$2"
    shift 2
    local command="$@"
    
    log_info "$function_name" "Starting background: $description"
    log_info "$function_name" "Background command: $command"
    
    if eval "$command &"; then
        local bg_pid=$!
        log_info "$function_name" "SUCCESS: $description started with PID $bg_pid"
        return 0
    else
        local exit_code=$?
        log_error "$function_name" "$command" "$exit_code" "$description failed to start"
        return $exit_code
    fi
}

# Trap for cleanup on exit
cleanup() {
    local exit_code=$?
    echo -e "\n${YELLOW}Cleanup triggered (exit code: $exit_code)${NC}"
    
    # Kill background processes gracefully
    log_info "cleanup" "Stopping background processes..."
    
    # Stop profiling tools
    sudo pkill -f "perf record" 2>/dev/null || true
    sudo pkill -f "py-spy record" 2>/dev/null || true
    sudo pkill -f "strace" 2>/dev/null || true
    sudo pkill -f "bpftrace" 2>/dev/null || true
    sudo pkill -f "execsnoop" 2>/dev/null || true
    
    # Wait for clean shutdown
    sleep 1
    
    # Print error summary
    if [ $ERRORS_ENCOUNTERED -gt 0 ]; then
        echo -e "\n${RED}=== ERROR SUMMARY ===${NC}"
        echo -e "${RED}Total errors encountered: $ERRORS_ENCOUNTERED${NC}"
        echo -e "${RED}Check $OUTPUT_DIR/error_log.txt for details${NC}"
        echo -e "$ERROR_LOG"
    else
        echo -e "\n${GREEN}No errors encountered during profiling${NC}"
    fi
    
    exit $exit_code
}

trap cleanup EXIT INT TERM

echo -e "${GREEN}=== Full System Profiling Tool ===${NC}"
echo "Duration: $DURATION seconds"
echo "Output directory: $OUTPUT_DIR"

# Create output directory with error handling
if ! mkdir -p "$OUTPUT_DIR"; then
    echo -e "${RED}FATAL: Failed to create output directory: $OUTPUT_DIR${NC}" >&2
    exit 1
fi

# Initialize log files
touch "$OUTPUT_DIR/error_log.txt" "$OUTPUT_DIR/debug_log.txt"
log_info "main" "Profiling started with duration: $DURATION seconds"
log_info "main" "Output directory: $OUTPUT_DIR"

# Function to find process PIDs
find_process_pids() {
    echo -e "${YELLOW}Finding process PIDs...${NC}"
    log_info "find_process_pids" "Starting process discovery"
    
    # Find Controller process (may be sudo wrapper)
    if ! CONTROLLER_PID=$(pgrep -f "Controller" | head -1 2>/dev/null); then
        log_warning "find_process_pids" "Controller process not found with pgrep"
        CONTROLLER_PID=""
    fi
    
    if [ -z "$CONTROLLER_PID" ]; then
        log_warning "find_process_pids" "Controller process not found"
    else
        log_info "find_process_pids" "Controller PID found: $CONTROLLER_PID"
        echo "Controller PID: $CONTROLLER_PID"
    fi
    
    # Find the actual Python Controller process (not sudo wrapper)
    if ! PYTHON_CONTROLLER_PID=$(ps aux | grep "python3 src/Controller" | grep -v "sudo python3" | awk '{print $2}' | head -1 2>/dev/null); then
        log_warning "find_process_pids" "Python Controller process not found with ps"
        PYTHON_CONTROLLER_PID=""
    fi
    
    if [ -z "$PYTHON_CONTROLLER_PID" ]; then
        log_warning "find_process_pids" "Python Controller process not found"
        # Fallback: use CONTROLLER_PID if it's actually the Python process
        if [ ! -z "$CONTROLLER_PID" ]; then
            if ps -p $CONTROLLER_PID -o comm= 2>/dev/null | grep -q python; then
                PYTHON_CONTROLLER_PID=$CONTROLLER_PID
                log_info "find_process_pids" "Using Controller PID as Python process: $PYTHON_CONTROLLER_PID"
                echo "Using Controller PID as Python process: $PYTHON_CONTROLLER_PID"
            fi
        fi
    else
        log_info "find_process_pids" "Python Controller PID found: $PYTHON_CONTROLLER_PID"
        echo "Python Controller PID: $PYTHON_CONTROLLER_PID"
    fi
    
    # Find smbsloweraod process
    if ! SMBSLOWER_PID=$(pgrep -f "smbsloweraod" | head -1 2>/dev/null); then
        log_warning "find_process_pids" "smbsloweraod process not found"
        SMBSLOWER_PID=""
    fi
    
    if [ -z "$SMBSLOWER_PID" ]; then
        log_warning "find_process_pids" "smbsloweraod process not found"
    else
        log_info "find_process_pids" "smbsloweraod PID found: $SMBSLOWER_PID"
        echo "smbsloweraod PID: $SMBSLOWER_PID"
    fi
    
    # Save process tree (use CONTROLLER_PID for hierarchy, even if it's sudo)
    if [ ! -z "$CONTROLLER_PID" ]; then
        if safe_exec "find_process_pids" "Generate process tree" \
           "pstree -p -t $CONTROLLER_PID > '$OUTPUT_DIR/process_tree.txt' 2>/dev/null"; then
            log_info "find_process_pids" "Process tree saved to process_tree.txt"
            echo "Process tree saved to process_tree.txt"
        else
            log_warning "find_process_pids" "Failed to generate process tree"
        fi
    else
        log_warning "find_process_pids" "No Controller PID available for process tree"
    fi
}

# Function to monitor dynamic subprocess creation
monitor_subprocess_creation() {
    echo -e "${YELLOW}Monitoring subprocess creation...${NC}"
    log_info "monitor_subprocess_creation" "Starting subprocess monitoring"
    
    # Check for execsnoop-bpfcc
    if command -v execsnoop-bpfcc >/dev/null 2>&1; then
        log_info "monitor_subprocess_creation" "Using execsnoop-bpfcc for monitoring"
        if safe_background_exec "monitor_subprocess_creation" "execsnoop monitoring" \
           "timeout $DURATION sudo execsnoop-bpfcc > '$OUTPUT_DIR/subprocess_creation.log' 2>&1"; then
            echo "execsnoop monitoring started"
        else
            log_warning "monitor_subprocess_creation" "execsnoop failed, trying bpftrace"
        fi
    # Check for bpftrace
    elif command -v bpftrace >/dev/null 2>&1; then
        log_info "monitor_subprocess_creation" "Using bpftrace for exec monitoring"
        if safe_background_exec "monitor_subprocess_creation" "bpftrace exec monitoring" \
           "timeout $DURATION sudo bpftrace -e 'tracepoint:syscalls:sys_enter_execve { printf(\"PID %d PPID %d: %s\\n\", pid, args->pid, str(args->filename)); }' > '$OUTPUT_DIR/subprocess_creation.log' 2>&1"; then
            echo "bpftrace exec monitoring started"
        else
            log_warning "monitor_subprocess_creation" "bpftrace failed, using fallback"
        fi
    else
        log_warning "monitor_subprocess_creation" "No eBPF tools available, using ps fallback"
    fi
    
    # Fallback: monitor with ps in a loop (always run as backup)
    log_info "monitor_subprocess_creation" "Starting ps fallback monitoring"
    if safe_background_exec "monitor_subprocess_creation" "ps snapshot monitoring" \
       "(echo 'timestamp,pid,ppid,command' > '$OUTPUT_DIR/process_snapshot.csv'; for i in \$(seq 1 $DURATION); do timestamp=\$(date +%s); ps -eo pid,ppid,comm --no-headers 2>/dev/null | while read pid ppid comm; do echo \"\$timestamp,\$pid,\$ppid,\$comm\" >> '$OUTPUT_DIR/process_snapshot.csv' 2>/dev/null || true; done; sleep 1; done)"; then
        echo "Process snapshot monitoring started"
    else
        log_error "monitor_subprocess_creation" "ps monitoring" "$?" "Failed to start ps fallback monitoring"
    fi
}

# Function to profile Python processes
profile_python_processes() {
    echo -e "${YELLOW}Profiling Python processes...${NC}"
    log_info "profile_python_processes" "Starting Python profiling"
    
    if ! command -v py-spy >/dev/null 2>&1; then
        log_error "profile_python_processes" "py-spy check" "127" "py-spy not available"
        return 1
    fi
    
    if [ -z "$PYTHON_CONTROLLER_PID" ]; then
        log_error "profile_python_processes" "PID check" "1" "No Python Controller process found for py-spy"
        return 1
    fi
    
    log_info "profile_python_processes" "Using Python Controller process for py-spy: $PYTHON_CONTROLLER_PID"
    echo "Using Python Controller process for py-spy: $PYTHON_CONTROLLER_PID"
    
    # Profile main Controller with all threads (SVG flamegraph)
    if safe_background_exec "profile_python_processes" "py-spy SVG profile" \
       "sudo py-spy record -o '$OUTPUT_DIR/controller_profile.svg' --pid $PYTHON_CONTROLLER_PID --duration $DURATION --threads"; then
        log_info "profile_python_processes" "SVG profiling started successfully"
    else
        log_warning "profile_python_processes" "SVG profiling failed"
    fi
    
    # Real-time sampling for detailed analysis (use raw format)
    if safe_background_exec "profile_python_processes" "py-spy detailed profile" \
       "sudo py-spy record -o '$OUTPUT_DIR/controller_detailed.txt' --format raw --pid $PYTHON_CONTROLLER_PID --duration $DURATION --rate 100 --threads"; then
        log_info "profile_python_processes" "Detailed profiling started successfully"
    else
        log_warning "profile_python_processes" "Detailed profiling failed"
    fi
    
    # Also profile with perf to catch native code that py-spy might miss
    if safe_background_exec "profile_python_processes" "perf profile for Python" \
       "sudo perf record -g -p $PYTHON_CONTROLLER_PID -o '$OUTPUT_DIR/python_native_profile.data'"; then
        log_info "profile_python_processes" "Perf profiling started successfully"
        echo "py-spy profiling started for Controller (Python + GIL-releasing native code)"
        echo "perf profiling started for Controller (all native code including NumPy internals)"
    else
        log_warning "profile_python_processes" "Perf profiling failed"
    fi
}

profile_system_processes() {
    echo -e "${YELLOW}Profiling system processes...${NC}"
    log_info "profile_system_processes" "Starting system process profiling"
    
    # Profile eBPF process if found
    if [ ! -z "$SMBSLOWER_PID" ]; then
        if safe_background_exec "profile_system_processes" "perf profile for smbsloweraod" \
           "sudo perf record -g -p $SMBSLOWER_PID -o '$OUTPUT_DIR/smbslower_profile.data'"; then
            log_info "profile_system_processes" "smbsloweraod profiling started"
            echo "perf profiling started for smbsloweraod"
        else
            log_warning "profile_system_processes" "smbsloweraod profiling failed"
        fi
    else
        log_warning "profile_system_processes" "No smbsloweraod process found for profiling"
    fi
    
    # System-wide profiling to catch all subprocesses
    if safe_background_exec "profile_system_processes" "system-wide perf profiling" \
       "sudo perf record -g -a -o '$OUTPUT_DIR/system_wide_profile.data'"; then
        log_info "profile_system_processes" "System-wide profiling started"
        echo "System-wide perf profiling started"
    else
        log_warning "profile_system_processes" "System-wide profiling failed"
    fi
    
    # Profile specific commands that LogCollector spawns
    if safe_background_exec "profile_system_processes" "subprocess execution profiling" \
       "sudo perf record -g -e 'syscalls:sys_enter_execve' -a -o '$OUTPUT_DIR/subprocess_profile.data'"; then
        log_info "profile_system_processes" "Subprocess execution profiling started"
        echo "Subprocess execution profiling started"
    else
        log_warning "profile_system_processes" "Subprocess execution profiling failed"
    fi
}

# Function to monitor detailed thread resource usage
monitor_thread_resources() {
    echo -e "${YELLOW}Monitoring detailed thread resources...${NC}"
    log_info "monitor_thread_resources" "Starting detailed thread monitoring"
    
    if [ -z "$PYTHON_CONTROLLER_PID" ]; then
        log_error "monitor_thread_resources" "PID check" "1" "No Python Controller process found for thread monitoring"
        return 1
    fi
    
    (
        if ! echo "timestamp,tid,thread_name,cpu_percent,mem_kb,cpu_time_user,cpu_time_system" > "$OUTPUT_DIR/detailed_thread_usage.csv"; then
            log_error "monitor_thread_resources" "CSV creation" "$?" "Failed to create detailed_thread_usage.csv"
            exit 1
        fi
        
        for i in $(seq 1 $DURATION); do
            timestamp=$(date +%s)
            
            # Use pidstat for accurate per-thread CPU% (if available)
            if command -v pidstat >/dev/null 2>&1; then
                log_info "monitor_thread_resources" "Using pidstat for thread monitoring at iteration $i"
                if pidstat_output=$(pidstat -t -p $PYTHON_CONTROLLER_PID 1 1 2>/dev/null); then
                    echo "$pidstat_output" | grep -v "^#\|^Average\|^$\|Linux" | while read line; do
                        if echo "$line" | grep -q "^[0-9]"; then
                            tid=$(echo "$line" | awk '{print $4}' 2>/dev/null || echo "-")
                            cpu_percent=$(echo "$line" | awk '{print $7}' 2>/dev/null || echo "-")
                            if [ "$tid" != "-" ] && [ "$cpu_percent" != "-" ]; then
                                # Get thread name and memory info
                                if [ -f "/proc/$PYTHON_CONTROLLER_PID/task/$tid/comm" ]; then
                                    thread_name=$(cat "/proc/$PYTHON_CONTROLLER_PID/task/$tid/comm" 2>/dev/null || echo "unknown")
                                    # Get memory info from /proc/PID/task/TID/status
                                    mem_kb=$(grep "VmRSS" "/proc/$PYTHON_CONTROLLER_PID/task/$tid/status" 2>/dev/null | awk '{print $2}' || echo "0")
                                    # Get detailed CPU times
                                    if [ -f "/proc/$PYTHON_CONTROLLER_PID/task/$tid/stat" ]; then
                                        cpu_times=$(cat "/proc/$PYTHON_CONTROLLER_PID/task/$tid/stat" 2>/dev/null | awk '{print $14","$15}' || echo "0,0")
                                    else
                                        cpu_times="0,0"
                                    fi
                                    echo "$timestamp,$tid,$thread_name,$cpu_percent,$mem_kb,$cpu_times" >> "$OUTPUT_DIR/detailed_thread_usage.csv" 2>/dev/null || \
                                        log_warning "monitor_thread_resources" "Failed to write detailed thread data for TID $tid at iteration $i"
                                fi
                            fi
                        fi
                    done
                else
                    log_warning "monitor_thread_resources" "pidstat failed at iteration $i, trying top fallback"
                fi
            else
                log_info "monitor_thread_resources" "pidstat not available, using top fallback"
            fi
            
            # Fallback: use top for thread monitoring if pidstat failed or not available
            if ! command -v pidstat >/dev/null 2>&1 || [ $? -ne 0 ]; then
                if top_output=$(top -b -n1 -H -p $PYTHON_CONTROLLER_PID 2>/dev/null); then
                    echo "$top_output" | grep -E "^\s*[0-9]+" | while read line; do
                        tid=$(echo "$line" | awk '{print $1}' 2>/dev/null || echo "0")
                        cpu_percent=$(echo "$line" | awk '{print $9}' 2>/dev/null || echo "0.0")
                        mem_percent=$(echo "$line" | awk '{print $10}' 2>/dev/null || echo "0.0")
                        if [ -f "/proc/$PYTHON_CONTROLLER_PID/task/$tid/comm" ]; then
                            thread_name=$(cat "/proc/$PYTHON_CONTROLLER_PID/task/$tid/comm" 2>/dev/null || echo "unknown")
                            echo "$timestamp,$tid,$thread_name,$cpu_percent,N/A,N/A,N/A" >> "$OUTPUT_DIR/detailed_thread_usage.csv" 2>/dev/null || \
                                log_warning "monitor_thread_resources" "Failed to write top fallback data for TID $tid at iteration $i"
                        fi
                    done
                else
                    log_warning "monitor_thread_resources" "Both pidstat and top failed at iteration $i"
                fi
            fi
            
            sleep 1
        done
    ) &
    log_info "monitor_thread_resources" "Detailed thread resource monitoring started successfully"
    echo "Detailed thread resource monitoring started (using pidstat/top)"
}

# Function to monitor resource usage
monitor_resources() {
    echo -e "${YELLOW}Monitoring resource usage...${NC}"
    log_info "monitor_resources" "Starting resource monitoring"
    
    # Create CSV headers with error handling
    if ! echo "timestamp,total_processes,controller_cpu,controller_mem,smbslower_cpu,smbslower_mem,journalctl_count,cat_count,total_tree_cpu,total_tree_mem" > "$OUTPUT_DIR/resource_usage.csv"; then
        log_error "monitor_resources" "CSV creation" "$?" "Failed to create resource_usage.csv"
        return 1
    fi
    
    if ! echo "timestamp,thread_count,thread_details" > "$OUTPUT_DIR/thread_info.csv"; then
        log_error "monitor_resources" "CSV creation" "$?" "Failed to create thread_info.csv"
        return 1
    fi
    
    if ! echo "timestamp,total_children,active_children,cpu_of_children" > "$OUTPUT_DIR/process_tree_usage.csv"; then
        log_error "monitor_resources" "CSV creation" "$?" "Failed to create process_tree_usage.csv"
        return 1
    fi
    
    log_info "monitor_resources" "CSV files created successfully"
    
    (
        for i in $(seq 1 $DURATION); do
            timestamp=$(date +%s)
            
            # Count total processes with error handling
            if ! total_processes=$(ps aux 2>/dev/null | wc -l); then
                log_warning "monitor_resources" "Failed to count total processes at iteration $i"
                total_processes=0
            fi
            
            # Get Controller stats (process-level, which includes all threads)
            if [ ! -z "$PYTHON_CONTROLLER_PID" ]; then
                if ! controller_stats=$(ps -p $PYTHON_CONTROLLER_PID -o %cpu,%mem --no-headers 2>/dev/null); then
                    log_warning "monitor_resources" "Failed to get controller stats at iteration $i"
                    controller_stats="0.0 0.0"
                fi
                
                # Calculate TOTAL CPU/Memory usage of entire process tree
                if command -v pstree >/dev/null 2>&1; then
                    # Get all PIDs in the process tree
                    if all_pids=$(pstree -p $PYTHON_CONTROLLER_PID 2>/dev/null | grep -o '([0-9]*)' | tr -d '()' | sort -u); then
                        total_tree_cpu=0
                        total_tree_mem=0
                        active_children=0
                        total_children=0
                        
                        for pid in $all_pids; do
                            if [ "$pid" != "$PYTHON_CONTROLLER_PID" ] && ps -p $pid >/dev/null 2>&1; then
                                total_children=$((total_children + 1))
                                # Get CPU and memory for each child process
                                if child_stats=$(ps -p $pid -o %cpu,%mem --no-headers 2>/dev/null); then
                                    child_cpu=$(echo $child_stats | awk '{print $1}' 2>/dev/null || echo "0.0")
                                    child_mem=$(echo $child_stats | awk '{print $2}' 2>/dev/null || echo "0.0")
                                    # Use bc for floating point arithmetic if available, otherwise awk
                                    if command -v bc >/dev/null 2>&1; then
                                        total_tree_cpu=$(echo "$total_tree_cpu + $child_cpu" | bc 2>/dev/null || echo "$total_tree_cpu")
                                        total_tree_mem=$(echo "$total_tree_mem + $child_mem" | bc 2>/dev/null || echo "$total_tree_mem")
                                    else
                                        total_tree_cpu=$(awk "BEGIN {print $total_tree_cpu + $child_cpu}" 2>/dev/null || echo "$total_tree_cpu")
                                        total_tree_mem=$(awk "BEGIN {print $total_tree_mem + $child_mem}" 2>/dev/null || echo "$total_tree_mem")
                                    fi
                                    if [ "$(echo "$child_cpu > 0" | bc 2>/dev/null || awk "BEGIN {print ($child_cpu > 0)}" 2>/dev/null || echo "0")" = "1" ]; then
                                        active_children=$((active_children + 1))
                                    fi
                                fi
                            fi
                        done
                        
                        # Add controller's own CPU/Memory to tree totals
                        controller_cpu=$(echo $controller_stats | awk '{print $1}' 2>/dev/null || echo "0.0")
                        controller_mem=$(echo $controller_stats | awk '{print $2}' 2>/dev/null || echo "0.0")
                        if command -v bc >/dev/null 2>&1; then
                            total_tree_cpu=$(echo "$total_tree_cpu + $controller_cpu" | bc 2>/dev/null || echo "$total_tree_cpu")
                            total_tree_mem=$(echo "$total_tree_mem + $controller_mem" | bc 2>/dev/null || echo "$total_tree_mem")
                        else
                            total_tree_cpu=$(awk "BEGIN {print $total_tree_cpu + $controller_cpu}" 2>/dev/null || echo "$total_tree_cpu")
                            total_tree_mem=$(awk "BEGIN {print $total_tree_mem + $controller_mem}" 2>/dev/null || echo "$total_tree_mem")
                        fi
                        
                        echo "$timestamp,$total_children,$active_children,$total_tree_cpu" >> "$OUTPUT_DIR/process_tree_usage.csv" 2>/dev/null || \
                            log_warning "monitor_resources" "Failed to write process tree data at iteration $i"
                    else
                        log_warning "monitor_resources" "pstree failed at iteration $i"
                        total_tree_cpu="0.0"
                        total_tree_mem="0.0"
                    fi
                else
                    # Fallback without pstree: look for common child processes
                    if child_pids=$(pgrep -P $PYTHON_CONTROLLER_PID 2>/dev/null); then
                        controller_cpu=$(echo $controller_stats | awk '{print $1}' 2>/dev/null || echo "0.0")
                        controller_mem=$(echo $controller_stats | awk '{print $2}' 2>/dev/null || echo "0.0")
                        total_tree_cpu=$controller_cpu
                        total_tree_mem=$controller_mem
                        active_children=0
                        total_children=0
                        
                        for pid in $child_pids; do
                            total_children=$((total_children + 1))
                            if child_stats=$(ps -p $pid -o %cpu,%mem --no-headers 2>/dev/null); then
                                child_cpu=$(echo $child_stats | awk '{print $1}' 2>/dev/null || echo "0.0")
                                child_mem=$(echo $child_stats | awk '{print $2}' 2>/dev/null || echo "0.0")
                                total_tree_cpu=$(awk "BEGIN {print $total_tree_cpu + $child_cpu}" 2>/dev/null || echo "$total_tree_cpu")
                                total_tree_mem=$(awk "BEGIN {print $total_tree_mem + $child_mem}" 2>/dev/null || echo "$total_tree_mem")
                                if [ "$(awk "BEGIN {print ($child_cpu > 0)}" 2>/dev/null || echo "0")" = "1" ]; then
                                    active_children=$((active_children + 1))
                                fi
                            fi
                        done
                        
                        echo "$timestamp,$total_children,$active_children,$total_tree_cpu" >> "$OUTPUT_DIR/process_tree_usage.csv" 2>/dev/null || \
                            log_warning "monitor_resources" "Failed to write fallback process tree data at iteration $i"
                    else
                        total_tree_cpu="0.0"
                        total_tree_mem="0.0"
                    fi
                fi
                
                # Count threads and get thread names (but not individual CPU - that's misleading)
                if [ -d "/proc/$PYTHON_CONTROLLER_PID/task" ]; then
                    if thread_count=$(ls /proc/$PYTHON_CONTROLLER_PID/task 2>/dev/null | wc -l); then
                        # Get thread names using our set_thread_name() function
                        if thread_names=$(ps -p $PYTHON_CONTROLLER_PID -L -o comm= 2>/dev/null | sort | uniq | tr '\n' '|'); then
                            echo "$timestamp,$thread_count,$thread_names" >> "$OUTPUT_DIR/thread_info.csv" 2>/dev/null || \
                                log_warning "monitor_resources" "Failed to write thread info at iteration $i"
                        else
                            echo "$timestamp,$thread_count,unknown" >> "$OUTPUT_DIR/thread_info.csv" 2>/dev/null || \
                                log_warning "monitor_resources" "Failed to write thread info (unknown names) at iteration $i"
                        fi
                        
                        # Capture thread CPU time accumulation (better than instantaneous %)
                        if [ $i -eq 1 ]; then  # First iteration - create thread CPU tracking file
                            if ! echo "timestamp,tid,thread_name,total_cpu_time,cpu_percent" > "$OUTPUT_DIR/thread_cpu_time.csv"; then
                                log_error "monitor_resources" "thread CPU CSV creation" "$?" "Failed to create thread_cpu_time.csv"
                            fi
                        fi
                        
                        for task_dir in /proc/$PYTHON_CONTROLLER_PID/task/*; do
                            if [ -d "$task_dir" ]; then
                                tid=$(basename "$task_dir")
                                comm=$(cat "$task_dir/comm" 2>/dev/null || echo "unknown")
                                # Get cumulative CPU time (user + system) from /proc/PID/task/TID/stat
                                cpu_time=$(cat "$task_dir/stat" 2>/dev/null | awk '{print $14+$15}' || echo "0")
                                
                                # Calculate CPU percentage using pidstat if available
                                if command -v pidstat >/dev/null 2>&1; then
                                    cpu_percent=$(pidstat -t -p $PYTHON_CONTROLLER_PID 1 1 2>/dev/null | grep -w "$tid" | awk '{print $7}' | tail -1 || echo "0.0")
                                else
                                    # Fallback: try top for this specific thread
                                    cpu_percent=$(top -b -n1 -H -p $PYTHON_CONTROLLER_PID 2>/dev/null | grep -w "$tid" | awk '{print $9}' | head -1 || echo "0.0")
                                fi
                                
                                echo "$timestamp,$tid,$comm,$cpu_time,$cpu_percent" >> "$OUTPUT_DIR/thread_cpu_time.csv" 2>/dev/null || \
                                    log_warning "monitor_resources" "Failed to write thread CPU data for TID $tid at iteration $i"
                            fi
                        done
                    else
                        log_warning "monitor_resources" "Failed to count threads at iteration $i"
                        thread_count=1
                        echo "$timestamp,$thread_count,count_failed" >> "$OUTPUT_DIR/thread_info.csv" 2>/dev/null
                    fi
                else
                    thread_count=1
                    echo "$timestamp,$thread_count,main_only" >> "$OUTPUT_DIR/thread_info.csv" 2>/dev/null || \
                        log_warning "monitor_resources" "Failed to write main-only thread info at iteration $i"
                fi
            else
                controller_stats="0.0 0.0"
                total_tree_cpu="0.0"
                total_tree_mem="0.0"
                echo "$timestamp,0,no_process" >> "$OUTPUT_DIR/thread_info.csv" 2>/dev/null || \
                    log_warning "monitor_resources" "Failed to write no-process info at iteration $i"
            fi
            
            # Get smbsloweraod stats
            if [ ! -z "$SMBSLOWER_PID" ]; then
                if ! smbslower_stats=$(ps -p $SMBSLOWER_PID -o %cpu,%mem --no-headers 2>/dev/null); then
                    log_warning "monitor_resources" "Failed to get smbslower stats at iteration $i"
                    smbslower_stats="0.0 0.0"
                fi
            else
                smbslower_stats="0.0 0.0"
            fi
            
            # Count LogCollector subprocess instances (more comprehensive)
            journalctl_count=$(pgrep -c journalctl 2>/dev/null || echo 0)
            cat_count=$(pgrep -c "cat" 2>/dev/null || echo 0)
            
            echo "$timestamp,$total_processes,$controller_stats,$smbslower_stats,$journalctl_count,$cat_count,$total_tree_cpu,$total_tree_mem" >> "$OUTPUT_DIR/resource_usage.csv" 2>/dev/null || \
                log_warning "monitor_resources" "Failed to write main resource data at iteration $i"
            
            sleep 1
        done
    ) &
    MONITOR_PID=$!
    log_info "monitor_resources" "Resource monitoring background process started with PID $MONITOR_PID"
    echo "Resource monitoring started (process-level with complete tree CPU tracking)"
}

# Function to monitor complete process tree in detail
monitor_process_tree() {
    echo -e "${YELLOW}Monitoring complete process tree...${NC}"
    
    if [ ! -z "$PYTHON_CONTROLLER_PID" ]; then
        (
            echo "timestamp,level,pid,ppid,command,cpu_percent,mem_percent,cumulative_cpu" > "$OUTPUT_DIR/complete_tree_usage.csv"
            
            for i in $(seq 1 $DURATION); do
                timestamp=$(date +%s)
                
                # Get complete process tree with levels
                if command -v pstree >/dev/null; then
                    # Use pstree to get hierarchical view, then get stats for each process
                    pstree -p $PYTHON_CONTROLLER_PID 2>/dev/null | grep -o '([0-9]*)' | tr -d '()' | while read pid; do
                        if ps -p $pid >/dev/null 2>&1; then
                            # Get process info
                            process_info=$(ps -p $pid -o pid,ppid,comm,%cpu,%mem,time --no-headers 2>/dev/null)
                            if [ ! -z "$process_info" ]; then
                                ppid=$(echo "$process_info" | awk '{print $2}')
                                command=$(echo "$process_info" | awk '{print $3}')
                                cpu_percent=$(echo "$process_info" | awk '{print $4}')
                                mem_percent=$(echo "$process_info" | awk '{print $5}')
                                cumulative_cpu=$(echo "$process_info" | awk '{print $6}')
                                
                                # Determine level in tree (0=root, 1=child, 2=grandchild, etc.)
                                if [ "$pid" = "$PYTHON_CONTROLLER_PID" ]; then
                                    level=0
                                elif [ "$ppid" = "$PYTHON_CONTROLLER_PID" ]; then
                                    level=1
                                else
                                    level=2  # Simplified - could be deeper
                                fi
                                
                                echo "$timestamp,$level,$pid,$ppid,$command,$cpu_percent,$mem_percent,$cumulative_cpu" >> "$OUTPUT_DIR/complete_tree_usage.csv"
                            fi
                        fi
                    done
                else
                    # Fallback: manual tree traversal
                    # Level 0: Main process
                    process_info=$(ps -p $PYTHON_CONTROLLER_PID -o pid,ppid,comm,%cpu,%mem,time --no-headers 2>/dev/null)
                    if [ ! -z "$process_info" ]; then
                        echo "$timestamp,0,$process_info" >> "$OUTPUT_DIR/complete_tree_usage.csv"
                    fi
                    
                    # Level 1: Direct children
                    pgrep -P $PYTHON_CONTROLLER_PID 2>/dev/null | while read child_pid; do
                        process_info=$(ps -p $child_pid -o pid,ppid,comm,%cpu,%mem,time --no-headers 2>/dev/null)
                        if [ ! -z "$process_info" ]; then
                            echo "$timestamp,1,$process_info" >> "$OUTPUT_DIR/complete_tree_usage.csv"
                        fi
                        
                        # Level 2: Grandchildren
                        pgrep -P $child_pid 2>/dev/null | while read grandchild_pid; do
                            process_info=$(ps -p $grandchild_pid -o pid,ppid,comm,%cpu,%mem,time --no-headers 2>/dev/null)
                            if [ ! -z "$process_info" ]; then
                                echo "$timestamp,2,$process_info" >> "$OUTPUT_DIR/complete_tree_usage.csv"
                            fi
                        done
                    done
                fi
                
                sleep 1
            done
        ) &
        echo "Complete process tree monitoring started (captures short-lived processes)"
    else
        echo -e "${RED}No Python Controller process found for tree monitoring${NC}"
    fi
}

# Function to monitor LogCollector async tasks
monitor_asyncio_activity() {
    echo -e "${YELLOW}Monitoring AsyncIO activity...${NC}"
    log_info "monitor_asyncio_activity" "Starting AsyncIO activity monitoring"
    
    if ! command -v strace >/dev/null 2>&1; then
        log_error "monitor_asyncio_activity" "strace check" "127" "strace not available"
        return 1
    fi
    
    if [ ! -z "$PYTHON_CONTROLLER_PID" ]; then
        log_info "monitor_asyncio_activity" "Using Python Controller PID for strace: $PYTHON_CONTROLLER_PID"
        # Monitor system calls from Python Controller process and ALL its threads/children
        # -f follows forks and threads, ensuring we catch all subprocess creation
        if safe_background_exec "monitor_asyncio_activity" "strace monitoring for Python Controller" \
           "timeout $DURATION sudo strace -f -p $PYTHON_CONTROLLER_PID -e trace=execve,clone,fork,vfork -o '$OUTPUT_DIR/controller_syscalls.log' 2>&1"; then
            echo "strace monitoring started for Python Controller PID $PYTHON_CONTROLLER_PID (including all threads)"
        else
            log_warning "monitor_asyncio_activity" "strace failed for Python Controller PID"
        fi
    elif [ ! -z "$CONTROLLER_PID" ]; then
        log_info "monitor_asyncio_activity" "Using fallback Controller PID for strace: $CONTROLLER_PID"
        # Fallback to the original CONTROLLER_PID if Python-specific search fails
        if safe_background_exec "monitor_asyncio_activity" "strace monitoring for Controller (fallback)" \
           "timeout $DURATION sudo strace -f -p $CONTROLLER_PID -e trace=execve,clone,fork,vfork -o '$OUTPUT_DIR/controller_syscalls.log' 2>&1"; then
            echo "strace monitoring started for Controller PID $CONTROLLER_PID (fallback)"
        else
            log_warning "monitor_asyncio_activity" "strace failed for fallback Controller PID"
        fi
    else
        log_error "monitor_asyncio_activity" "PID check" "1" "No Controller process found for strace monitoring"
        return 1
    fi
}

# Function to monitor eBPF activity
monitor_ebpf_activity() {
    echo -e "${YELLOW}Monitoring eBPF activity...${NC}"
    log_info "monitor_ebpf_activity" "Starting eBPF activity monitoring"
    
    # Monitor eBPF programs and maps with error handling
    if safe_exec "monitor_ebpf_activity" "Capture initial eBPF programs" \
       "sudo bpftool prog list > '$OUTPUT_DIR/ebpf_programs_start.txt' 2>/dev/null"; then
        log_info "monitor_ebpf_activity" "Initial eBPF programs captured"
    else
        log_warning "monitor_ebpf_activity" "Failed to capture initial eBPF programs"
    fi
    
    if safe_exec "monitor_ebpf_activity" "Capture initial eBPF maps" \
       "sudo bpftool map list > '$OUTPUT_DIR/ebpf_maps_start.txt' 2>/dev/null"; then
        log_info "monitor_ebpf_activity" "Initial eBPF maps captured"
    else
        log_warning "monitor_ebpf_activity" "Failed to capture initial eBPF maps"
    fi
    
    if command -v bpftrace >/dev/null 2>&1; then
        log_info "monitor_ebpf_activity" "Starting bpftrace monitoring"
        if safe_background_exec "monitor_ebpf_activity" "bpftrace eBPF activity monitoring" \
           "timeout $DURATION sudo bpftrace -e 'BEGIN { printf(\"Monitoring eBPF activity for LogCollector system\\n\"); } tracepoint:bpf:* { printf(\"%s: %s\\n\", strftime(\"%H:%M:%S\", nsecs), probe); }' > '$OUTPUT_DIR/ebpf_activity.log' 2>&1"; then
            echo "eBPF activity monitoring started"
        else
            log_warning "monitor_ebpf_activity" "bpftrace monitoring failed"
        fi
    else
        log_warning "monitor_ebpf_activity" "bpftrace not available, skipping eBPF activity monitoring"
    fi
}

# Main execution
echo -e "${GREEN}Starting comprehensive profiling...${NC}"
log_info "main" "Starting comprehensive profiling"

# Execute functions with error handling
log_info "main" "Step 1: Finding process PIDs"
if ! find_process_pids; then
    log_error "main" "find_process_pids" "$?" "Process PID discovery failed"
    echo -e "${RED}Warning: Process discovery failed, some monitoring may not work${NC}"
fi

log_info "main" "Step 2: Starting subprocess creation monitoring"
if ! monitor_subprocess_creation; then
    log_error "main" "monitor_subprocess_creation" "$?" "Subprocess monitoring failed to start"
    echo -e "${RED}Warning: Subprocess monitoring failed${NC}"
fi

log_info "main" "Step 3: Starting Python process profiling"
if ! profile_python_processes; then
    log_error "main" "profile_python_processes" "$?" "Python profiling failed to start"
    echo -e "${RED}Warning: Python profiling failed${NC}"
fi

log_info "main" "Step 4: Starting system process profiling"
if ! profile_system_processes; then
    log_error "main" "profile_system_processes" "$?" "System profiling failed to start"
    echo -e "${RED}Warning: System profiling failed${NC}"
fi

log_info "main" "Step 5: Starting resource monitoring"
if ! monitor_resources; then
    log_error "main" "monitor_resources" "$?" "Resource monitoring failed to start"
    echo -e "${RED}Warning: Resource monitoring failed${NC}"
fi

log_info "main" "Step 6: Starting thread resource monitoring"
if ! monitor_thread_resources; then
    log_error "main" "monitor_thread_resources" "$?" "Thread monitoring failed to start"
    echo -e "${RED}Warning: Thread monitoring failed${NC}"
fi

log_info "main" "Step 7: Starting process tree monitoring"
if ! monitor_process_tree; then
    log_error "main" "monitor_process_tree" "$?" "Process tree monitoring failed to start"
    echo -e "${RED}Warning: Process tree monitoring failed${NC}"
fi

log_info "main" "Step 8: Starting AsyncIO activity monitoring"
if ! monitor_asyncio_activity; then
    log_error "main" "monitor_asyncio_activity" "$?" "AsyncIO monitoring failed to start"
    echo -e "${RED}Warning: AsyncIO monitoring failed${NC}"
fi

log_info "main" "Step 9: Starting eBPF activity monitoring"
if ! monitor_ebpf_activity; then
    log_error "main" "monitor_ebpf_activity" "$?" "eBPF monitoring failed to start"
    echo -e "${RED}Warning: eBPF monitoring failed${NC}"
fi

echo -e "${GREEN}All monitoring started. Waiting $DURATION seconds...${NC}"
echo "Press Ctrl+C to stop early"
log_info "main" "All monitoring processes started, waiting $DURATION seconds"

# Wait for profiling duration
if ! sleep $DURATION; then
    log_warning "main" "Sleep interrupted, stopping profiling early"
fi

echo -e "${YELLOW}Stopping all profiling...${NC}"
log_info "main" "Stopping all profiling processes"

# Stop all background jobs gracefully
log_info "cleanup" "Stopping perf processes"
sudo pkill -f "perf record" 2>/dev/null || log_warning "cleanup" "No perf processes found to stop"

log_info "cleanup" "Stopping py-spy processes"
sudo pkill -f "py-spy record" 2>/dev/null || log_warning "cleanup" "No py-spy processes found to stop"

log_info "cleanup" "Stopping strace processes"
sudo pkill -f "strace" 2>/dev/null || log_warning "cleanup" "No strace processes found to stop"

log_info "cleanup" "Stopping bpftrace processes"
sudo pkill -f "bpftrace" 2>/dev/null || log_warning "cleanup" "No bpftrace processes found to stop"

log_info "cleanup" "Stopping execsnoop processes"
sudo pkill -f "execsnoop" 2>/dev/null || log_warning "cleanup" "No execsnoop processes found to stop"

# Wait a moment for clean shutdown
sleep 2

# Generate reports with error handling
echo -e "${YELLOW}Generating reports...${NC}"
log_info "main" "Starting report generation"

# Generate perf reports
perf_reports_generated=0
for data_file in "$OUTPUT_DIR"/*.data; do
    if [ -f "$data_file" ]; then
        report_file="${data_file%.data}_report.txt"
        log_info "report_generation" "Generating report for $(basename $data_file)"
        if safe_exec "report_generation" "Generate perf report for $(basename $data_file)" \
           "sudo perf report -i '$data_file' --stdio > '$report_file' 2>/dev/null"; then
            echo "Generated report: $(basename $report_file)"
            perf_reports_generated=$((perf_reports_generated + 1))
        else
            log_warning "report_generation" "Failed to generate report for $(basename $data_file)"
        fi
    fi
done

log_info "report_generation" "Generated $perf_reports_generated perf reports"

# Capture final system state with error handling
log_info "report_generation" "Capturing final system state"
if ! sudo bpftool prog list > "$OUTPUT_DIR/ebpf_programs_end.txt" 2>/dev/null; then
    log_warning "report_generation" "Failed to capture eBPF programs end state"
fi

if ! sudo bpftool map list > "$OUTPUT_DIR/ebpf_maps_end.txt" 2>/dev/null; then
    log_warning "report_generation" "Failed to capture eBPF maps end state"
fi

# System information with error handling
log_info "report_generation" "Collecting system information"
if ! uname -a > "$OUTPUT_DIR/system_info.txt" 2>/dev/null; then
    log_warning "report_generation" "Failed to collect uname info"
fi

if ! cat /proc/version >> "$OUTPUT_DIR/system_info.txt" 2>/dev/null; then
    log_warning "report_generation" "Failed to collect kernel version"
fi

if ! lscpu > "$OUTPUT_DIR/cpu_info.txt" 2>/dev/null; then
    log_warning "report_generation" "Failed to collect CPU info"
fi

if ! free -h > "$OUTPUT_DIR/memory_info.txt" 2>/dev/null; then
    log_warning "report_generation" "Failed to collect memory info"
fi

# Process summary with error handling
if [ ! -z "$CONTROLLER_PID" ]; then
    if ! ps -p $CONTROLLER_PID -f > "$OUTPUT_DIR/final_controller_info.txt" 2>/dev/null; then
        log_warning "report_generation" "Failed to collect final controller info"
    fi
fi

if [ ! -z "$SMBSLOWER_PID" ]; then
    if ! ps -p $SMBSLOWER_PID -f > "$OUTPUT_DIR/final_smbslower_info.txt" 2>/dev/null; then
        log_warning "report_generation" "Failed to collect final smbslower info"
    fi
fi

log_info "main" "Profiling completed successfully"

echo -e "${GREEN}=== Profiling Complete! ===${NC}"
echo "Results saved in: $OUTPUT_DIR"

# Error summary before file listing
if [ $ERRORS_ENCOUNTERED -gt 0 ]; then
    echo ""
    echo -e "${RED}=== ERRORS ENCOUNTERED: $ERRORS_ENCOUNTERED ===${NC}"
    echo -e "${RED}Check $OUTPUT_DIR/error_log.txt for detailed error information${NC}"
    echo -e "${YELLOW}Some monitoring features may have failed, but partial data was collected${NC}"
    echo ""
fi

echo ""
echo -e "${YELLOW}Generated files:${NC}"

# List files with error handling and size information
files_found=0
if [ -f "$OUTPUT_DIR/controller_profile.svg" ]; then
    file_size=$(du -h "$OUTPUT_DIR/controller_profile.svg" 2>/dev/null | cut -f1 || echo "?")
    echo "📊 controller_profile.svg ($file_size) - Interactive Python profile (open in browser)"
    files_found=$((files_found + 1))
fi

if [ -f "$OUTPUT_DIR/resource_usage.csv" ]; then
    lines=$(wc -l < "$OUTPUT_DIR/resource_usage.csv" 2>/dev/null || echo "?")
    echo "📈 resource_usage.csv ($lines lines) - CPU/Memory usage over time"
    files_found=$((files_found + 1))
fi

if [ -f "$OUTPUT_DIR/thread_info.csv" ]; then
    lines=$(wc -l < "$OUTPUT_DIR/thread_info.csv" 2>/dev/null || echo "?")
    echo "🧵 thread_info.csv ($lines lines) - Thread count and names over time"
    files_found=$((files_found + 1))
fi

if [ -f "$OUTPUT_DIR/thread_cpu_time.csv" ]; then
    lines=$(wc -l < "$OUTPUT_DIR/thread_cpu_time.csv" 2>/dev/null || echo "?")
    echo "⏱️ thread_cpu_time.csv ($lines lines) - Cumulative CPU time per thread (better than %)"
    files_found=$((files_found + 1))
fi

if [ -f "$OUTPUT_DIR/detailed_thread_usage.csv" ]; then
    lines=$(wc -l < "$OUTPUT_DIR/detailed_thread_usage.csv" 2>/dev/null || echo "?")
    echo "📊 detailed_thread_usage.csv ($lines lines) - Per-thread CPU% and memory (pidstat/top based)"
    files_found=$((files_found + 1))
fi

if [ -f "$OUTPUT_DIR/subprocess_creation.log" ]; then
    lines=$(wc -l < "$OUTPUT_DIR/subprocess_creation.log" 2>/dev/null || echo "?")
    echo "🔍 subprocess_creation.log ($lines lines) - All subprocess creation events"
    files_found=$((files_found + 1))
fi

# Count perf reports
perf_reports=$(ls "$OUTPUT_DIR"/*_profile_report.txt 2>/dev/null | wc -l)
if [ $perf_reports -gt 0 ]; then
    echo "⚡ *_profile_report.txt ($perf_reports files) - Performance analysis reports"
    files_found=$((files_found + perf_reports))
fi

if [ -f "$OUTPUT_DIR/process_tree.txt" ]; then
    echo "🧵 process_tree.txt - Process hierarchy"
    files_found=$((files_found + 1))
fi

# Count eBPF files
ebpf_files=$(ls "$OUTPUT_DIR"/ebpf_*.txt 2>/dev/null | wc -l)
if [ $ebpf_files -gt 0 ]; then
    echo "🔧 ebpf_*.txt ($ebpf_files files) - eBPF program and map information"
    files_found=$((files_found + ebpf_files))
fi

if [ -f "$OUTPUT_DIR/controller_syscalls.log" ]; then
    lines=$(wc -l < "$OUTPUT_DIR/controller_syscalls.log" 2>/dev/null || echo "?")
    echo "🔍 controller_syscalls.log ($lines lines) - System call trace"
    files_found=$((files_found + 1))
fi

if [ -f "$OUTPUT_DIR/error_log.txt" ]; then
    lines=$(wc -l < "$OUTPUT_DIR/error_log.txt" 2>/dev/null || echo "?")
    echo "❌ error_log.txt ($lines lines) - Error and warning log"
    files_found=$((files_found + 1))
fi

if [ -f "$OUTPUT_DIR/debug_log.txt" ]; then
    lines=$(wc -l < "$OUTPUT_DIR/debug_log.txt" 2>/dev/null || echo "?")
    echo "🐛 debug_log.txt ($lines lines) - Debug information log"
    files_found=$((files_found + 1))
fi

echo ""
echo -e "${BLUE}Total files generated: $files_found${NC}"

echo ""
echo -e "${YELLOW}Quick analysis commands:${NC}"
if [ -f "$OUTPUT_DIR/controller_profile.svg" ]; then
    echo "View Python profile: firefox $OUTPUT_DIR/controller_profile.svg"
fi
echo "Real-time py-spy: sudo py-spy top --pid [PID]"
echo "Thread CPU over time: top -H -p [PID] (press H for threads, 1 for per-CPU)"
echo "Detailed thread stats: cat /proc/[PID]/task/*/stat"
if [ -f "$OUTPUT_DIR/resource_usage.csv" ]; then
    echo "Analyze resource usage: python3 -c \"import pandas as pd; df=pd.read_csv('$OUTPUT_DIR/resource_usage.csv'); print(df.describe())\""
fi
if [ -f "$OUTPUT_DIR/subprocess_creation.log" ]; then
    echo "Check subprocess activity: grep -E '(journalctl|cat|exec)' $OUTPUT_DIR/subprocess_creation.log | head -20"
fi

echo ""
echo -e "${YELLOW}Troubleshooting:${NC}"
echo "Check errors: cat $OUTPUT_DIR/error_log.txt"
echo "Check debug info: cat $OUTPUT_DIR/debug_log.txt"
echo "Verify process PIDs: ps aux | grep -E '(Controller|python3|smbslower)'"

if [ $ERRORS_ENCOUNTERED -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Profiling completed successfully with no errors!${NC}"
    exit 0
else
    echo ""
    echo -e "${YELLOW}⚠️ Profiling completed with $ERRORS_ENCOUNTERED errors/warnings${NC}"
    echo -e "${YELLOW}Check error logs for details, but partial data was collected${NC}"
    exit 1
fi
