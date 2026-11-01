# M10 Operations, observability, hardening and deployment

**Phase:** P5 · **Size:** M · **Parallelism:** observability (one session), hardening (one session), deployment docs and backup (one session).
**Requirements:** REQ-25 (application-level reviews), REQ-01

## Purpose
Make the application operable and defensible: logging, metrics, tracing, health, backups and restore, production Compose profile, TLS, security headers, rate limiting, dependency and image scanning in CI, release process and runbooks.

## Scope
In: structured JSON logs with request ids, Prometheus metrics (HTTP latency, queue depth, capture success rate, items per hour, output failures), OpenTelemetry traces optional, `/health` and `/ready`, backup script (pg_dump plus object store) and documented restore drill, production Compose with resource limits and read-only filesystems, Caddy with HSTS, CSP, frame-ancestors, referrer policy, rate limiting on auth and search, secrets via Docker secrets or environment, CI gates for Trivy, pip-audit, npm audit, Semgrep, gitleaks, license scan, SBOM generation (CycloneDX, Apache-2.0 tooling), release notes from CHANGELOG, runbooks.
Out: Kubernetes (backlog), multi-region.

## Open-source components
structlog (MIT), prometheus-client (Apache-2.0), OpenTelemetry (Apache-2.0), Caddy (Apache-2.0), Trivy (Apache-2.0), Semgrep CLI (LGPL-2.1, tooling), gitleaks (MIT), cyclonedx-python and cyclonedx-npm (Apache-2.0), Grafana and Prometheus (tooling, optional), pgBackRest (MIT) optional for larger databases.

## Acceptance criteria
1. A restore drill from last night's backup on a clean host brings the application up with identical item counts, documented step by step.
2. Security headers score A on a header scanner; CSP blocks inline scripts except the theme bootstrap nonce.
3. CI blocks a PR introducing a critical CVE in an image or dependency, or a prohibited license.
4. Dashboards show capture success rate and output failures; an alert fires when a source is unhealthy for 24 hours.
5. SBOM published with each release.

## Test plan
- Integration: production Compose profile boots with read-only root filesystems; health and readiness semantics under database outage.
- Security: OWASP ZAP baseline and full scan against staging; Semgrep with OWASP rulesets; manual review of Caddy config.
- Load: k6 scenario of 10 concurrent users browsing the map and searching for 15 minutes with p95 within budgets.
- Chaos: kill a worker mid-run and confirm the run is marked failed and rescheduled; kill Valkey and confirm API degrades gracefully.

## Question bank
1. Who operates the system and what monitoring stack do they already run? Default: owner; Prometheus and Grafana optional.
2. Backup destination and retention? Default: local volume plus optional S3-compatible bucket, 30 days.
3. Required uptime and maintenance windows? Default: business hours, weekly maintenance window.
4. Is a vulnerability disclosure contact needed in `SECURITY.md`? Default: owner email.

## Enhancements to propose
Kubernetes Helm chart; blue-green deploys; status page.
