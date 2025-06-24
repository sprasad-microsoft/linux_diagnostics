#!/bin/bash

# Simple AOD Resource Monitor
# Monitors CPU/Memory usage of AOD processes and /var/log/aod/batches directory size

set -euo pipefail

# Configuration
DURATION=${1:-60}  # Default 60 seconds
OUTPUT_DIR="aod_monitoring_$(date +%Y%m%d_%H%M%S)"
BATCHES_DIR="/var/log/aod/batches"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== AOD Resource Monitor ===${NC}"
echo "Duration: $DURATION seconds"
echo "Output directory: $OUTPUT_DIR"
echo "Batches directory: $BATCHES_DIR"

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Find AOD processes
find_aod_processes() {
    # Find Python Controller process (main AOD process)
    CONTROLLER_PID=$(pgrep -f "python3.*Controller" | head -1 2>/dev/null || echo "")
    
    if [ -z "$CONTROLLER_PID" ]; then
        echo -e "${RED}Warning: No AOD Controller process found${NC}"
        return 1
    fi
    
    echo "Found AOD Controller PID: $CONTROLLER_PID"
    return 0
}

# Monitor AOD process tree resources
monitor_aod_resources() {
    echo "timestamp,total_processes,total_cpu_percent,total_mem_percent,total_mem_kb" > "$OUTPUT_DIR/aod_resources.csv"
    
    for i in $(seq 1 $DURATION); do
        timestamp=$(date +%s)
        
        if [ ! -z "$CONTROLLER_PID" ] && ps -p $CONTROLLER_PID >/dev/null 2>&1; then
            # Get all PIDs in the process tree
            if command -v pstree >/dev/null 2>&1; then
                # Use pstree to get complete process tree
                all_pids=$(pstree -p $CONTROLLER_PID 2>/dev/null | grep -o '([0-9]*)' | tr -d '()' | sort -u)
            else
                # Fallback: get direct children only
                all_pids="$CONTROLLER_PID $(pgrep -P $CONTROLLER_PID 2>/dev/null | tr '\n' ' ')"
            fi
            
            total_cpu=0
            total_mem_percent=0
            total_mem_kb=0
            process_count=0
            
            for pid in $all_pids; do
                if ps -p $pid >/dev/null 2>&1; then
                    # Get CPU% and Memory% from ps
                    stats=$(ps -p $pid -o %cpu,%mem --no-headers 2>/dev/null || echo "0.0 0.0")
                    cpu=$(echo $stats | awk '{print $1}' || echo "0.0")
                    mem_percent=$(echo $stats | awk '{print $2}' || echo "0.0")
                    
                    # Get memory in KB from /proc
                    mem_kb=$(grep "VmRSS" /proc/$pid/status 2>/dev/null | awk '{print $2}' || echo "0")
                    
                    # Sum up totals (using awk for floating point arithmetic)
                    total_cpu=$(awk "BEGIN {print $total_cpu + $cpu}")
                    total_mem_percent=$(awk "BEGIN {print $total_mem_percent + $mem_percent}")
                    total_mem_kb=$((total_mem_kb + mem_kb))
                    process_count=$((process_count + 1))
                fi
            done
            
            echo "$timestamp,$process_count,$total_cpu,$total_mem_percent,$total_mem_kb" >> "$OUTPUT_DIR/aod_resources.csv"
        else
            echo "$timestamp,0,0.0,0.0,0" >> "$OUTPUT_DIR/aod_resources.csv"
        fi
        
        sleep 1
    done
}

# Monitor /var/log/aod/batches directory size
monitor_batches_directory() {
    echo "timestamp,size_bytes,size_mb,file_count" > "$OUTPUT_DIR/batches_directory.csv"
    
    for i in $(seq 1 $DURATION); do
        timestamp=$(date +%s)
        
        if [ -d "$BATCHES_DIR" ]; then
            # Get directory size in bytes
            size_bytes=$(du -sb "$BATCHES_DIR" 2>/dev/null | cut -f1 || echo "0")
            size_mb=$(awk "BEGIN {printf \"%.2f\", $size_bytes/1024/1024}")
            
            # Count files in directory
            file_count=$(find "$BATCHES_DIR" -type f 2>/dev/null | wc -l || echo "0")
            
            echo "$timestamp,$size_bytes,$size_mb,$file_count" >> "$OUTPUT_DIR/batches_directory.csv"
        else
            echo "$timestamp,0,0.00,0" >> "$OUTPUT_DIR/batches_directory.csv"
        fi
        
        sleep 1
    done
}

# Real-time display (optional - runs in background)
realtime_display() {
    echo -e "${YELLOW}Starting real-time display (press Ctrl+C to stop)${NC}"
    
    while sleep 5; do
        if [ -f "$OUTPUT_DIR/aod_resources.csv" ] && [ -f "$OUTPUT_DIR/batches_directory.csv" ]; then
            # Get latest resource data
            latest_resources=$(tail -1 "$OUTPUT_DIR/aod_resources.csv" 2>/dev/null)
            latest_batches=$(tail -1 "$OUTPUT_DIR/batches_directory.csv" 2>/dev/null)
            
            if [ ! -z "$latest_resources" ] && [ ! -z "$latest_batches" ]; then
                processes=$(echo $latest_resources | cut -d',' -f2)
                cpu=$(echo $latest_resources | cut -d',' -f3)
                mem_mb=$(echo $latest_resources | cut -d',' -f5 | awk '{printf "%.1f", $1/1024}')
                
                batches_mb=$(echo $latest_batches | cut -d',' -f3)
                file_count=$(echo $latest_batches | cut -d',' -f4)
                
                echo "$(date '+%H:%M:%S') - AOD: ${processes} processes, ${cpu}% CPU, ${mem_mb}MB RAM | Batches: ${batches_mb}MB, ${file_count} files"
            fi
        fi
    done
}

# Main execution
echo -e "${YELLOW}Finding AOD processes...${NC}"
if ! find_aod_processes; then
    echo -e "${RED}Cannot find AOD processes. Make sure AOD is running.${NC}"
    exit 1
fi

echo -e "${YELLOW}Starting monitoring for $DURATION seconds...${NC}"

# Start monitoring in background
monitor_aod_resources &
AOD_PID=$!

monitor_batches_directory &
BATCHES_PID=$!

# Start real-time display (optional)
realtime_display &
DISPLAY_PID=$!

# Wait for monitoring to complete
wait $AOD_PID
wait $BATCHES_PID

# Stop real-time display
kill $DISPLAY_PID 2>/dev/null || true

echo -e "${GREEN}Monitoring complete!${NC}"
echo "Results saved in: $OUTPUT_DIR"
echo ""
echo "Generated files:"
echo "📊 aod_resources.csv - AOD process CPU/Memory usage over time"
echo "📁 batches_directory.csv - /var/log/aod/batches directory size over time"
echo ""
echo "Quick analysis commands:"
echo "# Show resource usage summary:"
echo "awk -F',' 'NR>1 {cpu+=$3; mem+=$5; count++} END {printf \"Avg CPU: %.2f%%, Avg Memory: %.1fMB\\n\", cpu/count, mem/count/1024}' $OUTPUT_DIR/aod_resources.csv"
echo ""
echo "# Show batches directory growth:"
echo "awk -F',' 'NR>1 {print $1, $3}' $OUTPUT_DIR/batches_directory.csv | tail -5"
echo ""
echo "# Peak resource usage:"
echo "awk -F',' 'NR>1 {if($3>max_cpu) max_cpu=$3; if($5>max_mem) max_mem=$5} END {printf \"Peak CPU: %.2f%%, Peak Memory: %.1fMB\\n\", max_cpu, max_mem/1024}' $OUTPUT_DIR/aod_resources.csv"
