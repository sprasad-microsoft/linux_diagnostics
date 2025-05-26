#!/bin/bash
# preuninstall.sh - Script to stop and disable the Linux diagnostics controller daemon before package removal

# Stop the service if it is running
if systemctl is-active --quiet linux_diagnostics.service; then
    systemctl stop linux_diagnostics.service
fi

# Disable the service to prevent it from starting on boot
systemctl disable linux_diagnostics.service

# Optionally, remove the PID file if it exists
PIDFILE="/var/run/linux_diagnostics/controller.pid"
if [ -f "$PIDFILE" ]; then
    rm -f "$PIDFILE"
fi