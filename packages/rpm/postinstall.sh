#!/bin/bash
# postinstall.sh - Script to run after the RPM package is installed

# Enable and start the systemd service for the Linux diagnostics controller daemon
systemctl enable linux_diagnostics.service
systemctl start linux_diagnostics.service

echo "Linux diagnostics controller daemon has been installed and started."