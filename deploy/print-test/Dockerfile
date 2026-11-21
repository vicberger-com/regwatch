# A test IPP printer for development and QA only (CP-33, BL-145; M8 acceptance 3): CUPS's
# ippeveprinter from Debian's cups-ipp-utils (Apache-2.0), unmodified, as a separate service.
# Profile `print-test`; on the internal network only, with no published port.
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc
RUN apt-get update \
    && apt-get install -y --no-install-recommends cups-ipp-utils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10631 printer
USER printer
WORKDIR /home/printer
# -k keeps jobs for inspection; -r off: no DNS-SD; PDF accepted; port 631.
CMD ["ippeveprinter", "-p", "631", "-r", "off", "-k", "-d", "/home/printer/spool", "-f", "application/pdf", "regwatch-test"]
