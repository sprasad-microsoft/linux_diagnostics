# Makefile for building DEB and RPM packages

.PHONY: all debian rpm clean

all: debian rpm

debian:
	cd packages/debian && dpkg-buildpackage -us -uc

rpm:
	cd packages/rpm && rpmbuild -ba linux_diagnostics.spec

clean:
	cd packages/debian && dpkg-buildpackage -k
	cd packages/rpm && rm -rf *.rpm *.src.rpm
