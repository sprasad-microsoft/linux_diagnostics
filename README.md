# Linux Diagnostics Controller Daemon

This project is a Linux diagnostics controller daemon that monitors system performance and runs diagnostics based on specified anomalies. It is designed to be packaged for easy installation on Debian and RPM-based systems.

## Project Structure

- `src/linux_diagnostics_controller`: Contains the main logic for the Linux diagnostics controller daemon, handling configuration and diagnostics execution.
- `config/config.yaml`: Configuration file for the daemon. Users can customize the behavior of the diagnostics controller here.
- `packages/debian/`: Contains files necessary for building the DEB package.
  - `control`: Package metadata including name, version, maintainer, dependencies, and description.
  - `postinst`: Script executed after the DEB package is installed to enable and start the systemd service.
  - `prerm`: Script executed before the DEB package is removed to stop and disable the systemd service.
  - `rules`: Defines the build process for the DEB package.
- `packages/rpm/`: Contains files necessary for building the RPM package.
  - `linux_diagnostics.spec`: RPM package specification including name, version, release, summary, license, and installation/uninstallation scripts.
  - `postinstall.sh`: Script executed after the RPM package is installed to enable and start the systemd service.
  - `preuninstall.sh`: Script executed before the RPM package is removed to stop and disable the systemd service.
- `README.md`: Documentation for the project.
- `Makefile`: Defines the build commands for creating the DEB and RPM packages.

## Instructions to Build Packages

### Build DEB Package
1. Navigate to the project root directory:
   ```
   cd /path/to/linux_diagnostics
   ```
2. Run the following command to build the DEB package:
   ```
   make debian
   ```
3. The DEB package will be created in the parent directory of `packages/debian`.

### Build RPM Package
1. Navigate to the project root directory:
   ```
   cd /path/to/linux_diagnostics
   ```
2. Run the following command to build the RPM package:
   ```
   make rpm
   ```
3. The RPM package will be created in the `~/rpmbuild/RPMS/noarch/` directory.

## Installing the Packages

### Install DEB Package
1. Use `dpkg` to install the DEB package:
   ```
   sudo dpkg -i ../linux_diagnostics_1.0-1_all.deb
   ```
2. If there are missing dependencies, resolve them using:
   ```
   sudo apt-get install -f
   ```

### Install RPM Package
1. Use `rpm` to install the RPM package:
   ```
   sudo rpm -ivh ~/rpmbuild/RPMS/noarch/linux_diagnostics-1.0-1.noarch.rpm
   ```

## Managing the Service
After installation, the `linux_diagnostics` service will be installed and managed by `systemd`.

### Start the Service
```
sudo systemctl start linux_diagnostics.service
```

### Enable the Service to Start on Boot
```
sudo systemctl enable linux_diagnostics.service
```

### Check the Service Status
```
sudo systemctl status linux_diagnostics.service
```

### Stop the Service
```
sudo systemctl stop linux_diagnostics.service
```

## Uninstalling the Packages

### Uninstall DEB Package
```
sudo dpkg -r linux_diagnostics
```

### Uninstall RPM Package
```
sudo rpm -e linux_diagnostics
```

## Cleaning Up
To clean up build artifacts, run:
```
make clean
```

## License
This project is licensed under the MIT License.