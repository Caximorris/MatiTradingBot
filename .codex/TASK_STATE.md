# V7 OKX Demo cutover

Current milestone: integrate the reviewed narrow V7 commit set through the protected GitHub workflow.

Completed:

- Preserved the exchange-independent certified V7 core.
- Added a hash-chained, exclusive OKX Demo ownership lease.
- Added mocked V6 audit/evidence/guarded-stop and V7 preflight/activation contracts.
- Added a V7-specific demo execution adapter that rejects any non-demo client.
- Completed CLI-CUTOVER: deterministic, hash-chained, dependency-injected local cutover commands with mocked tests.
- Completed V7-DEMO-SERVICE: isolated certified-demo systemd definition, runner validation, and injected VM service wrappers.
- Completed CUTOVER-RUNBOOK-E2E: operator runbook and mocked end-to-end cutover coverage.

Next:

1. Integrate the reviewed, narrow V7 commit set into main and publish through protected GitHub workflow.

Do not access the VM, send orders, start/stop services, or mutate runtime state while developing.
