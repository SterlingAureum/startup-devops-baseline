# DemoApiLatencyErrorBudgetSlowBurn

## Meaning

The 99% <= 500 ms latency SLO is consuming its error budget persistently across long paired windows.

## Triage

1. Review the 2h/1d and 6h/3d latency burn-rate pairs and request volume.
2. Identify whether the degradation follows a release, dependency pattern, or capacity trend.
3. Create a remediation item with an owner and deadline based on remaining budget.

## Recovery

Close only after the paired windows recover and the sustained latency cause is tracked or removed.
