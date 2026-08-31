# DemoApiAvailabilityErrorBudgetFastBurn

## Meaning

The `GET /version` availability SLO is consuming its 0.1% error budget at a page-worthy rate. Both a short and long window are above threshold, which filters isolated spikes.

## Triage

1. Confirm both availability burn-rate series and current traffic in the Demo API SLO Dashboard.
2. Inspect the `5xx` status classes by release and compare stable with canary.
3. Correlate the first breach with Rollout, application, PostgreSQL, and platform events.
4. Mitigate the active fault; do not change the SLO objective to silence the alert.

## Recovery

The alert resolves only after the paired windows fall below threshold. Record the consumed budget and incident evidence before closing.
