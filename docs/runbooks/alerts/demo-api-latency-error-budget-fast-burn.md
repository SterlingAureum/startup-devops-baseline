# DemoApiLatencyErrorBudgetFastBurn

## Meaning

More than the allowed share of `GET /version` requests is exceeding 500 ms at a page-worthy rate. Both a short and long window must breach.

## Triage

1. Confirm the paired latency burn rates and request volume in the SLO Dashboard.
2. Compare stable and canary releases, then inspect application, PostgreSQL, node, and ingress latency.
3. Correlate traces and logs for slow requests and mitigate the active bottleneck.

## Recovery

The alert resolves after both paired windows fall below threshold. Preserve trace evidence and budget impact for the incident record.
