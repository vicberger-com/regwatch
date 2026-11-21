#!/bin/sh
# D-Bus and avahi for ippeveprinter's DNS-SD (no announcement leaves the internal network),
# then the printer as `printer` (its name is the container's hostname, which it checks the Host
# header against; compose.yaml sets it), -k
# keeps jobs for inspection, PDF accepted, port 631.
set -e
rm -f /run/dbus/pid /run/avahi-daemon/pid  # left by an earlier run of this container
dbus-daemon --system --fork
avahi-daemon --daemonize --no-chroot
install -d -o printer -g printer /home/printer/spool
exec setpriv --reuid=printer --regid=printer --init-groups \
    ippeveprinter -p 631 -k -d /home/printer/spool -f application/pdf regwatch-test
