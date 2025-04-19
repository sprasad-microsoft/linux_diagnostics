Name: linux_diagnostics
Version: 1.0
Release: 1%{?dist}
Summary: Linux Diagnostics Controller Daemon
License: MIT
Group: System/Daemons
BuildArch: x86_64
Requires: systemd

%description
This package installs the Linux Diagnostics Controller Daemon, its systemd service, and configuration file.

%prep

%build

%install
# Create necessary directories
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/etc/linux_diagnostics
mkdir -p %{buildroot}/lib/systemd/system

# Install the controller daemon
install -m 0755 src/controller %{buildroot}/usr/bin/controller

# Install the configuration file
install -m 0644 config/config.yaml %{buildroot}/etc/linux_diagnostics/config.yaml

# Install the systemd service file
install -m 0644 src/linux_diagnostics.service %{buildroot}/lib/systemd/system/linux_diagnostics.service

%files
%license LICENSE
/usr/bin/controller
/etc/linux_diagnostics/config.yaml
/lib/systemd/system/linux_diagnostics.service

%post
# Reload systemd to recognize the new service
%systemd_post linux_diagnostics.service

%preun
# Stop and disable the service before uninstalling
%systemd_preun linux_diagnostics.service

%postun
# Reload systemd after uninstalling
%systemd_postun linux_diagnostics.service
