# A test IPP printer for development and QA only (CP-33, BL-145; M8 acceptance 3): CUPS's
# ippeveprinter from Debian's cups-ipp-utils (Apache-2.0), unmodified, as a separate service.
# Profile `print-test`; on the internal network only, with no published port. Debian's build
# needs DNS-SD, so D-Bus and avahi run in the container too; the printer itself runs as an
# unprivileged user.
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
RUN apt-get update \
    && apt-get install -y --no-install-recommends cups-ipp-utils avahi-daemon dbus util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10631 printer \
    && mkdir -p /run/dbus
COPY start.sh /start.sh
CMD ["/bin/sh", "/start.sh"]
