Name: linux_diagnostics
Version: 1.0
Release: 1%{?dist}
Summary: Linux Diagnostics Controller Daemon
License: MIT
Source0: %{name}-%{version}.tar.gz

BuildArch: noarch
BuildRequires: python3, python3-setuptools
Requires: python3, systemd

%description
Linux Diagnostics Controller Daemon monitors anomalies and runs diagnostics.

%prep
%setup -q

%build
python3 setup.py build

%install
python3 setup.py install --root=%{buildroot} --prefix=/usr

# Install the systemd service file
install -D -m 644 src/linux_diagnostics.service %{buildroot}/usr/lib/systemd/system/linux_diagnostics.service

# Install the configuration file
install -D -m 644 config/config.yaml %{buildroot}/etc/linux_diagnostics/config.yaml

# Install the controller script
install -D -m 755 src/controller %{buildroot}/usr/bin/linux_diagnostics_controller

# Ensure the output directory exists
mkdir -p %{buildroot}/var/log/linux_diagnostics

%post
# Enable and start the service
systemctl enable linux_diagnostics.service
systemctl start linux_diagnostics.service || :

%preun
# Stop the service before uninstalling
if [ $1 -eq 0 ]; then
    systemctl stop linux_diagnostics.service || :
fi

%files
%license LICENSE
%doc README.md
/usr/lib/systemd/system/linux_diagnostics.service
/etc/linux_diagnostics/config.yaml
/usr/bin/linux_diagnostics_controller
/var/log/linux_diagnostics
%{python3_sitelib}/linux_diagnostics*

%changelog
* Wed Apr 30 2025 Shyam Prasad N <sprasad@microsoft.com> - 1.0-1
- Initial RPM package