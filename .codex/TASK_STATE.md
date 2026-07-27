# V7 OKX Demo cutover

Current milestone: implement and locally test the V6-to-V7 shared-demo-account cutover.

Completed:

- Preserved the exchange-independent certified V7 core.
- Added a hash-chained, exclusive OKX Demo ownership lease.
- Added mocked V6 audit/evidence/guarded-stop and V7 preflight/activation contracts.
- Added a V7-specific demo execution adapter that rejects any non-demo client.

Next:

1. Complete the VM-facing command wrappers and dedicated V7 service without touching V6.
2. Expand the operator runbook and mocked end-to-end tests.
3. Integrate the reviewed, narrow V7 commit set into main and publish through protected GitHub workflow.

Do not access the VM, send orders, start/stop services, or mutate runtime state while developing.
