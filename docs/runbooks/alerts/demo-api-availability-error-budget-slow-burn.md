# DemoApiAvailabilityErrorBudgetSlowBurn

## Meaning

The `GET /version` availability SLO is consuming its 0.1% error budget persistently. This warning is ticket-oriented and uses long paired windows.

## Triage

1. Compare the 2h/1d and 6h/3d burn-rate pairs in the SLO Dashboard.
2. Break down `5xx` traffic by release and inspect recurring dependency or rollout symptoms.
3. Assign an owner and remediation deadline based on remaining 30-day budget.

## Recovery

Close only after the paired windows recover and the underlying recurring cause has a tracked remediation.
