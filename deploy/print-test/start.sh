#!/bin/sh
# D-Bus and avahi for ippeveprinter's DNS-SD (no announcement leaves the internal network),
# then the printer as `printer`: named as the stack calls it (it checks the Host header), -k
# keeps jobs for inspection, PDF accepted, port 631.
set -e
dbus-daemon --system --fork
avahi-daemon --daemonize --no-chroot
exec setpriv --reuid=printer --regid=printer --init-groups \
    ippeveprinter -n ippeveprinter -p 631 -k -d /home/printer/spool -f application/pdf regwatch-test
