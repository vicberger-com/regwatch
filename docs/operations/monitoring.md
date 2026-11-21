# Monitoring (M10.5; M10 acceptance 4)

**Start:** add the `monitoring` profile to the production stack:
```
docker compose -f deploy/compose.prod.yaml --profile monitoring up -d
```
Grafana's admin password must be in `deploy/monitoring.env` (`GF_SECURITY_ADMIN_PASSWORD=…`), which is git-ignored and never committed. Without it the profile does not start.

**Reach Grafana** on the host at `http://127.0.0.1:3000`. From another machine, use a tunnel, never a wider port: `ssh -L 3000:127.0.0.1:3000 <host>`. Prometheus has no published port. Both sit on their own internal `monitoring` network, which the API joins for its metrics, so Grafana can reach Prometheus and nothing else in the stack, and Prometheus only the API's metrics. Grafana runs only its Prometheus data source; the other bundled ones are disabled, and so is plugin installation. Both keep 30 days of data. Grafana's session cookie is not marked secure, because it is served as plain HTTP on loopback. If it is ever put behind TLS or published more widely, set `GF_SECURITY_COOKIE_SECURE=true` and restrict who can reach it. Grafana's own limit on login attempts stays on.

## Dashboard: "regwatch overview"

| Panel | Shows |
| --- | --- |
| Capture success rate, 24 h | Successful and partial runs over all runs finished in the last 24 hours ("No runs in 24 h" when nothing ran) |
| Sources unhealthy for 24 h | Enabled sources marked unhealthy, with no good run in 24 hours |
| Outputs failed, 24 h | Failed output jobs in the last 24 hours, in total and by kind (PDF, email, CSV, print) |
| Items changed, last hour | Items whose content changed in the last hour |
| Capture runs, by outcome | Runs in the last 24 hours by status |
| Queue depth | Tasks waiting in each Celery queue (capture, process, outputs) |
| API latency, 95th percentile | Over 5 minutes, all routes |

## Alerts (`deploy/monitoring/alerts.yml`)

The alerts are unit-tested by `make monitoring-test`, which also runs in CI. They show in Grafana and in Prometheus. Sending them out (email, chat) is not set up; it is proposed as E19.

| Alert | Fires when | What to do |
| --- | --- | --- |
| SourceUnhealthyFor24Hours | A source has been unhealthy with no good run for 24 hours, for 5 minutes (acceptance 4) | Settings, Sources: read the source's last error, then fix or disable the source |
| OutputsFailing | 5 or more outputs failed in 24 hours, for 15 minutes | Outputs history: the error class names the printer, the mail server or the PDF service |
| QueueBacklog | A queue holds more than 100 tasks, for 15 minutes | Check the worker containers and their logs, and scale `worker` |
| CaptureFailingMostly | Over half of the capture runs failed in 24 hours, for 30 minutes | Look for a network or DNS problem on the `fetch` network |
| MetricsStale | The API has not refreshed its metrics for 5 minutes | `GET /api/v1/ready`: the database or the queue may be unreachable |
| ApiDown | Prometheus cannot reach the API's metrics, for 2 minutes | `docker compose ps`; read the api logs |

## Check of 2026-11-21

Prometheus and Grafana were run against the QA stack. The API target was up and all six rules loaded and were inactive. Grafana provisioned the dashboard and the data source, and answered 401 without sign-in. Every panel's query returned QA's values: no sources unhealthy; 4 print outputs failed, from the printing tests; queues empty; p95 latency 24 ms. The containers were then removed.
