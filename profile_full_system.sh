#!/bin/bash
# Comprehensive profiling script for multi-process Python + eBPF + subprocess system

# Configuration
DURATION=${1:-30}   #default duration is 30 seconds
OUTPUT_DIR="profiling_outputs/full_system_profile_$(date +%Y%m%d_%H%M%S)"
CONTROLLER_PID=""
PYTHON_CONTROLLER_PID=""
SMBSLOWER_PID=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Full System Profiling Tool ===${NC}"
echo "Duration: $DURATION seconds"
echo "Output directory: $OUTPUT_DIR"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Function to find process PIDs
find_process_pids() {
    echo -e "${YELLOW}Finding process PIDs...${NC}"
    
    # Find Controller process (may be sudo wrapper)
    CONTROLLER_PID=$(pgrep -f "Controller" | head -1)
    if [ -z "$CONTROLLER_PID" ]; then
        echo -e "${RED}Warning: Controller process not found${NC}"
    else
        echo "Controller PID: $CONTROLLER_PID"
    fi
    
    # Find the actual Python Controller process (not sudo wrapper)
    PYTHON_CONTROLLER_PID=$(ps aux | grep "python3 src/Controller" | grep -v "sudo python3" | awk '{print $2}' | head -1)
    if [ -z "$PYTHON_CONTROLLER_PID" ]; then
        echo -e "${RED}Warning: Python Controller process not found${NC}"
        # Fallback: use CONTROLLER_PID if it's actually the Python process
        if [ ! -z "$CONTROLLER_PID" ] && ps -p $CONTROLLER_PID -o comm= | grep -q python; then
            PYTHON_CONTROLLER_PID=$CONTROLLER_PID
            echo "Using Controller PID as Python process: $PYTHON_CONTROLLER_PID"
        fi
    else
        echo "Python Controller PID: $PYTHON_CONTROLLER_PID"
    fi
    
    # Find smbsloweraod process
    SMBSLOWER_PID=$(pgrep -f "smbsloweraod" | head -1)
    if [ -z "$SMBSLOWER_PID" ]; then
        echo -e "${RED}Warning: smbsloweraod process not found${NC}"
    else
        echo "smbsloweraod PID: $SMBSLOWER_PID"
    fi
    
    # Save process tree (use CONTROLLER_PID for hierarchy, even if it's sudo)
    if [ ! -z "$CONTROLLER_PID" ]; then
        pstree -p -t $CONTROLLER_PID > "$OUTPUT_DIR/process_tree.txt" 2>/dev/null
        echo "Process tree saved to process_tree.txt"
    fi
}

# Function to monitor dynamic subprocess creation
monitor_subprocess_creation() {
    echo -e "${YELLOW}Monitoring subprocess creation...${NC}"
    
    # Monitor process creation using execsnoop (if available)
    if command -v execsnoop-bpfcc >/dev/null; then
        timeout $DURATION sudo execsnoop-bpfcc > "$OUTPUT_DIR/subprocess_creation.log" 2>&1 &
        echo "execsnoop monitoring started"
    elif command -v bpftrace >/dev/null; then
        # Alternative: use bpftrace to monitor exec
        timeout $DURATION sudo bpftrace -e '
        tracepoint:syscalls:sys_enter_execve {
            printf("PID %d PPID %d: %s\n", pid, args->pid, str(args->filename));
        }
        ' > "$OUTPUT_DIR/subprocess_creation.log" 2>&1 &
        echo "bpftrace exec monitoring started"
    else
        # Fallback: monitor with ps in a loop
        (
            echo "timestamp,pid,ppid,command" > "$OUTPUT_DIR/process_snapshot.csv"
            for i in $(seq 1 $DURATION); do
                timestamp=$(date +%s)
                ps -eo pid,ppid,comm --no-headers | while read pid ppid comm; do
                    echo "$timestamp,$pid,$ppid,$comm" >> "$OUTPUT_DIR/process_snapshot.csv"
                done
                sleep 1
            done
        ) &
        echo "Process snapshot monitoring started"
    fi
}

# Function to profile Python processes
profile_python_processes() {
    echo -e "${YELLOW}Profiling Python processes...${NC}"
    
    if command -v py-spy >/dev/null; then
        if [ ! -z "$PYTHON_CONTROLLER_PID" ]; then
            echo "Using Python Controller process for py-spy: $PYTHON_CONTROLLER_PID"
            
            # Profile main Controller with all threads (SVG flamegraph)
            sudo py-spy record -o "$OUTPUT_DIR/controller_profile.svg" \
                --pid $PYTHON_CONTROLLER_PID --duration $DURATION --threads &
            
            # Real-time sampling for detailed analysis (use raw format)
            sudo py-spy record -o "$OUTPUT_DIR/controller_detailed.txt" \
                --format raw --pid $PYTHON_CONTROLLER_PID --duration $DURATION --rate 100 &
            
            echo "py-spy profiling started for Controller"
        else
            echo -e "${RED}No Python Controller process found for py-spy${NC}"
        fi
    else
        echo -e "${RED}py-spy not available${NC}"
    fi
}

# Function to profile system processes
profile_system_processes() {
    echo -e "${YELLOW}Profiling system processes...${NC}"
    
    # Profile eBPF process if found
    if [ ! -z "$SMBSLOWER_PID" ]; then
        sudo perf record -g -p $SMBSLOWER_PID -o "$OUTPUT_DIR/smbslower_profile.data" &
        echo "perf profiling started for smbsloweraod"
    fi
    
    # System-wide profiling to catch all subprocesses
    sudo perf record -g -a -o "$OUTPUT_DIR/system_wide_profile.data" &
    SYSTEM_PERF_PID=$!
    echo "System-wide perf profiling started"
    
    # Profile specific commands that LogCollector spawns
    sudo perf record -g -e 'syscalls:sys_enter_execve' -a -o "$OUTPUT_DIR/subprocess_profile.data" &
    echo "Subprocess execution profiling started"
}

# Function to monitor resource usage
monitor_resources() {
    echo -e "${YELLOW}Monitoring resource usage...${NC}"
    
    (
        echo "timestamp,total_processes,controller_cpu,controller_mem,smbslower_cpu,smbslower_mem,journalctl_count,cat_count" > "$OUTPUT_DIR/resource_usage.csv"
        echo "timestamp,thread_id,thread_name,cpu_percent,mem_percent" > "$OUTPUT_DIR/thread_usage.csv"
        
        for i in $(seq 1 $DURATION); do
            timestamp=$(date +%s)
            
            # Count total processes
            total_processes=$(ps aux | wc -l)
            
            # Get Controller stats
            if [ ! -z "$CONTROLLER_PID" ]; then
                controller_stats=$(ps -p $CONTROLLER_PID -o %cpu,%mem --no-headers 2>/dev/null || echo "0.0 0.0")
                
                # Monitor individual threads of Controller process
                if [ -d "/proc/$CONTROLLER_PID/task" ]; then
                    for thread_dir in /proc/$CONTROLLER_PID/task/*; do
                        if [ -d "$thread_dir" ]; then
                            thread_id=$(basename "$thread_dir")
                            # Get thread-specific CPU and memory usage
                            thread_stats=$(ps -p $thread_id -o %cpu,%mem,comm --no-headers 2>/dev/null || echo "0.0 0.0 unknown")
                            if [ "$thread_stats" != "0.0 0.0 unknown" ]; then
                                thread_cpu=$(echo "$thread_stats" | awk '{print $1}')
                                thread_mem=$(echo "$thread_stats" | awk '{print $2}')
                                thread_name=$(echo "$thread_stats" | awk '{print $3}')
                                echo "$timestamp,$thread_id,$thread_name,$thread_cpu,$thread_mem" >> "$OUTPUT_DIR/thread_usage.csv"
                            fi
                        fi
                    done
                fi
            else
                controller_stats="0.0 0.0"
            fi
            
            # Get smbsloweraod stats
            if [ ! -z "$SMBSLOWER_PID" ]; then
                smbslower_stats=$(ps -p $SMBSLOWER_PID -o %cpu,%mem --no-headers 2>/dev/null || echo "0.0 0.0")
            else
                smbslower_stats="0.0 0.0"
            fi
            
            # Count LogCollector subprocess instances
            journalctl_count=$(pgrep -c journalctl || echo 0)
            cat_count=$(pgrep -c "cat" || echo 0)
            
            echo "$timestamp,$total_processes,$controller_stats,$smbslower_stats,$journalctl_count,$cat_count" >> "$OUTPUT_DIR/resource_usage.csv"
            sleep 1
        done
    ) &
    MONITOR_PID=$!
    echo "Resource monitoring started (including per-thread analysis)"
}

# Function to monitor LogCollector async tasks
monitor_asyncio_activity() {
    echo -e "${YELLOW}Monitoring AsyncIO activity...${NC}"
    
    if command -v strace >/dev/null; then
        if [ ! -z "$PYTHON_CONTROLLER_PID" ]; then
            # Monitor system calls from Python Controller process and ALL its threads/children
            # -f follows forks and threads, ensuring we catch all subprocess creation
            timeout $DURATION sudo strace -f -p $PYTHON_CONTROLLER_PID -e trace=execve,clone,fork,vfork -o "$OUTPUT_DIR/controller_syscalls.log" 2>&1 &
            echo "strace monitoring started for Python Controller PID $PYTHON_CONTROLLER_PID (including all threads)"
        elif [ ! -z "$CONTROLLER_PID" ]; then
            # Fallback to the original CONTROLLER_PID if Python-specific search fails
            timeout $DURATION sudo strace -f -p $CONTROLLER_PID -e trace=execve,clone,fork,vfork -o "$OUTPUT_DIR/controller_syscalls.log" 2>&1 &
            echo "strace monitoring started for Controller PID $CONTROLLER_PID (fallback)"
        else
            echo -e "${RED}No Controller process found for strace monitoring${NC}"
        fi
    else
        echo -e "${RED}strace not available${NC}"
    fi
}

# Function to monitor eBPF activity
monitor_ebpf_activity() {
    echo -e "${YELLOW}Monitoring eBPF activity...${NC}"
    
    # Monitor eBPF programs and maps
    sudo bpftool prog list > "$OUTPUT_DIR/ebpf_programs_start.txt" 2>/dev/null
    sudo bpftool map list > "$OUTPUT_DIR/ebpf_maps_start.txt" 2>/dev/null
    
    if command -v bpftrace >/dev/null; then
        timeout $DURATION sudo bpftrace -e '
        BEGIN { printf("Monitoring eBPF activity for LogCollector system\n"); }
        tracepoint:bpf:* {
            printf("%s: %s\n", strftime("%H:%M:%S", nsecs), probe);
        }
        ' > "$OUTPUT_DIR/ebpf_activity.log" 2>&1 &
        echo "eBPF activity monitoring started"
    fi
}

# Main execution
echo -e "${GREEN}Starting comprehensive profiling...${NC}"

find_process_pids
monitor_subprocess_creation
profile_python_processes
profile_system_processes
monitor_resources
monitor_asyncio_activity
monitor_ebpf_activity

echo -e "${GREEN}All monitoring started. Waiting $DURATION seconds...${NC}"
echo "Press Ctrl+C to stop early"

# Wait for profiling duration
sleep $DURATION

echo -e "${YELLOW}Stopping all profiling...${NC}"

# Stop all background jobs
sudo pkill -f "perf record" 2>/dev/null
sudo pkill -f "py-spy record" 2>/dev/null
sudo pkill -f "strace" 2>/dev/null
sudo pkill -f "bpftrace" 2>/dev/null
sudo pkill -f "execsnoop" 2>/dev/null

# Wait a moment for clean shutdown
sleep 2

# Generate reports
echo -e "${YELLOW}Generating reports...${NC}"

# Generate perf reports
for data_file in "$OUTPUT_DIR"/*.data; do
    if [ -f "$data_file" ]; then
        report_file="${data_file%.data}_report.txt"
        sudo perf report -i "$data_file" --stdio > "$report_file" 2>/dev/null
        echo "Generated report: $(basename $report_file)"
    fi
done

# Capture final system state
sudo bpftool prog list > "$OUTPUT_DIR/ebpf_programs_end.txt" 2>/dev/null
sudo bpftool map list > "$OUTPUT_DIR/ebpf_maps_end.txt" 2>/dev/null

# System information
uname -a > "$OUTPUT_DIR/system_info.txt"
cat /proc/version >> "$OUTPUT_DIR/system_info.txt"
lscpu > "$OUTPUT_DIR/cpu_info.txt"
free -h > "$OUTPUT_DIR/memory_info.txt"

# Process summary
if [ ! -z "$CONTROLLER_PID" ]; then
    ps -p $CONTROLLER_PID -f > "$OUTPUT_DIR/final_controller_info.txt" 2>/dev/null
fi
if [ ! -z "$SMBSLOWER_PID" ]; then
    ps -p $SMBSLOWER_PID -f > "$OUTPUT_DIR/final_smbslower_info.txt" 2>/dev/null
fi

echo -e "${GREEN}=== Profiling Complete! ===${NC}"
echo "Results saved in: $OUTPUT_DIR"
echo ""
echo -e "${YELLOW}Generated files:${NC}"
echo "📊 controller_profile.svg - Interactive Python profile (open in browser)"
echo "📈 resource_usage.csv - CPU/Memory usage over time"
echo "🧵 thread_usage.csv - Per-thread CPU/Memory usage over time"
echo "🔍 subprocess_creation.log - All subprocess creation events"
echo "⚡ *_profile_report.txt - Performance analysis reports"
echo "🧵 process_tree.txt - Process hierarchy"
echo "🔧 ebpf_*.txt - eBPF program and map information"
if [ -f "$OUTPUT_DIR/controller_syscalls.log" ]; then
    echo "🔍 controller_syscalls.log - System call trace"
fi

echo ""
echo -e "${YELLOW}Quick analysis commands:${NC}"
echo "View Python profile: firefox $OUTPUT_DIR/controller_profile.svg"
echo "Analyze resource usage: python3 -c \"import pandas as pd; df=pd.read_csv('$OUTPUT_DIR/resource_usage.csv'); print(df.describe())\""
echo "Check subprocess activity: grep -E '(journalctl|cat|exec)' $OUTPUT_DIR/subprocess_creation.log | head -20"
