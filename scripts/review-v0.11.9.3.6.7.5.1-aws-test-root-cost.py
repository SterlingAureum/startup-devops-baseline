#!/usr/bin/env python3
"""Offline capacity/cost packet preparation and fresh Root-plan review. No live commands."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING, InvalidOperation
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "delivery/contracts/v0.11.9.3.6.7.5.1-aws-test-root-capacity-cost.json"
spec = importlib.util.spec_from_file_location("predecessor", ROOT / "scripts/check-v0.11.9.3.6.7.5-aws-test-recovery-root-plan.py")
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
RATE_KEYS = {"eks_hourly", "system_instance_hourly", "system_credit_hourly_total",
             "ebs_gib_hourly", "nat_gateway_hourly", "public_ipv4_hourly",
             "alb_hourly_with_lcu", "storage_backups_hourly", "logs_metrics_hourly",
             "dns_other_hourly", "transfer_hourly", "extra_ec2_hourly"}


def source_checks(root=ROOT):
    prior.source_checks(root)
    c = prior.load(root / CONTRACT)
    for item in c["reviewedFiles"]:
        prior.require(prior.digest(root / item["path"]) == item["sha256"], "predecessor-drift")
    prior.require(c["version"] == "v0.11.9.3.6.7.5.1", "version")
    prior.require(not any(c["operationBoundary"].values()), "offline-only")
    return c


def rate(item, now):
    value = prior.amount(item["usd"])
    age = (now - prior.utc(item["reviewed_at_utc"])).total_seconds()
    prior.require(0 <= age <= 86400, "price-review-expired-or-future")
    for key in ("reference", "coverage_note"):
        prior.require(isinstance(item[key], str) and len(item[key].strip()) >= 16
                      and "__" not in item[key], "price-source-and-coverage-required")
    return value


def estimate(profile, c, now):
    prior.require(profile["target_environment"] == "aws-test" and
                  profile["region"] == "us-east-1" and profile["currency"] == "USD", "price-target")
    prior.require(set(profile["rates"]) == RATE_KEYS, "price-components")
    names = {p["name"] for p in c["nodePools"]}
    prior.require(set(profile["pool_node_hourly_upper_usd"]) == names, "all-pool-prices-required")
    for key in ("all_eligible_instance_types_and_spot_fallback_reviewed",
                "all_ebs_snapshots_backups_transfer_and_lcu_reviewed"):
        prior.require(profile[key] is True, "price-scope-review-required")
    rates = {k: rate(v, now) for k, v in profile["rates"].items()}
    pools = {k: rate(v, now) for k, v in profile["pool_node_hourly_upper_usd"].items()}
    prior.require(all(v > 0 for k, v in rates.items() if k != "extra_ec2_hourly")
                  and all(v > 0 for v in pools.values()), "nonzero-resource-and-usage-bounds-required")
    prior.require(rates["eks_hourly"] >= Decimal("0.10") and
                  rates["public_ipv4_hourly"] >= Decimal("0.005"), "published-price-floor")
    overshoot = profile["overshoot_node_reserve"]
    extra_disk = profile["extra_ebs_gib"]
    ipv4 = profile["public_ipv4_count_upper"]
    prior.require(type(overshoot) is int and overshoot >= 1, "overshoot-reserve")
    prior.require(type(extra_disk) is int and extra_disk >= 0, "extra-volume-reserve")
    prior.require(type(ipv4) is int and ipv4 >= 3, "nat-and-alb-ipv4-reserve")
    fixed = prior.amount(profile["fixed_and_uncertainty_reserve_usd"])
    prior.require(fixed > 0, "fixed-uncertainty-reserve-required")
    baseline = c["baselineInventory"]
    pv = c["persistentVolumes"]
    configured_nodes = sum(p["configured_node_limit"] for p in c["nodePools"])
    disk = baseline["system_root_volume_gib"] + sum(
        p["configured_node_limit"] * p["root_disk_gib"] for p in c["nodePools"])
    disk += overshoot * 30 + pv["cnpg_instances"] * pv["cnpg_each_gib"]
    disk += pv["prometheus_gib"] + pv["alertmanager_gib"] + extra_disk
    ec2 = baseline["system_instance_count"] * rates["system_instance_hourly"]
    ec2 += rates["system_credit_hourly_total"] + rates["extra_ec2_hourly"]
    ec2 += sum(p["configured_node_limit"] * pools[p["name"]] for p in c["nodePools"])
    ec2 += overshoot * max(pools.values())
    components = {
        "eks": rates["eks_hourly"], "ec2": ec2, "ebs": disk * rates["ebs_gib_hourly"],
        "nat_and_ipv4": rates["nat_gateway_hourly"] + ipv4 * rates["public_ipv4_hourly"],
        "load_balancing": rates["alb_hourly_with_lcu"],
        "storage_backups": rates["storage_backups_hourly"],
        "logs_metrics": rates["logs_metrics_hourly"], "dns_and_other": rates["dns_other_hourly"],
        "transfer": rates["transfer_hourly"]}
    return components, fixed, {"configured_additional_node_limit_sum": configured_nodes,
                               "additional_node_estimate_with_overshoot": configured_nodes + overshoot,
                               "estimated_ebs_gib": disk,
                               "configured_limits_are_billing_hard_caps": False}


def report(profile, c, now, cleanup_end):
    components, fixed, capacity = estimate(profile, c, now)
    hourly = sum(components.values(), Decimal(0))
    anchor = prior.utc(c["accountingStartUtc"])
    available = prior.utc(c["operatorAvailableUntilUtc"])
    prior.require(now >= anchor, "accounting-start-is-future")
    prior.require(cleanup_end >= anchor, "cleanup-before-accounting-start")
    bound_seconds = ((Decimal("8") - fixed) / hourly * 3600).to_integral_value(rounding=ROUND_FLOOR)
    latest = min(anchor + timedelta(seconds=int(bound_seconds)), available,
                 now + timedelta(seconds=c["costRules"]["maximumWindowSeconds"]))
    elapsed = hourly * Decimal(str((now - anchor).total_seconds())) / 3600
    total = hourly * Decimal(str((cleanup_end - anchor).total_seconds())) / 3600 + fixed
    minimum = c["costRules"]["minimumRootWorkSeconds"] + c["costRules"]["minimumCleanupReserveSeconds"]
    fits = now + timedelta(seconds=minimum) <= cleanup_end <= latest
    cents = lambda x: str(x.quantize(Decimal("0.01"), rounding=ROUND_CEILING))
    return {"status": "aws-test-root-cost-model-fits-proposed-deadline" if fits else
            "aws-test-root-cost-model-does-not-fit-stop-for-review",
            "evaluated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "accounting_start_utc": c["accountingStartUtc"],
            "latest_cleanup_complete_by_utc": latest.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "requested_cleanup_complete_by_utc": cleanup_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "peak_hourly_estimate_usd": str(hourly), "elapsed_peak_cost_estimate_usd": cents(elapsed),
            "estimated_additional_cost_through_cleanup_usd": cents(total),
            "historical_spend_usd": None, "additional_budget_limit_usd": "8.00",
            "budget_model_fits": fits, "root_deployment_authorized": False,
            "live_commands_executed": False, "archived_observation_is_execution_input": False,
            "capacity": capacity}, components, fixed


def read_private(path):
    prior.private(path)
    prior.private(path.parent, 0o700)
    prior.persistent(path)
    return prior.load(path)


def review_plan(plan, observation, profile, c, now, price_hash, observation_hash):
    components, fixed, _ = estimate(profile, c, now)
    prior.require(plan["pricing_reference"] == "cost-profile-sha256:" + price_hash,
                  "plan-price-binding")
    prior.require(all(prior.amount(plan["hourly_upper_bound_usd"][k]) >= v
                      for k, v in components.items()) and
                  prior.amount(plan["fixed_and_uncertainty_reserve_usd"]) >= fixed, "underestimated-plan")
    prior.require(plan["observation_sha256"] == observation_hash, "fresh-plan-binding")
    prior.require(prior.utc(plan["cleanup_complete_by_utc"]) - prior.utc(plan["start_utc"]) >=
                  timedelta(seconds=plan["cleanup_reserve_seconds"] + 1800), "root-work-time-reserve")
    result = prior.check_plan(plan, observation, prior.source_checks(), now)
    result["cost_profile_sha256"] = price_hash
    result["next_action"] = "implement-and-review-immutable-bounded-root-deployment-executor"
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--cleanup-complete-by", required=True)
    prepare.add_argument("--output-directory", type=Path, required=True)
    review = sub.add_parser("review")
    review.add_argument("--plan", type=Path, required=True)
    for p in (prepare, review):
        p.add_argument("--pricing", type=Path, required=True)
        p.add_argument("--observation", type=Path, required=True)
        p.add_argument("--expected-observation-sha256", required=True)
    args = parser.parse_args()
    try:
        c = source_checks()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        profile = read_private(args.pricing)
        observation = read_private(args.observation)
        prior.require(prior.digest(args.observation) == args.expected_observation_sha256, "observation-hash")
        if args.phase == "prepare":
            archived = c["archivedObservation"]
            prior.require(args.expected_observation_sha256 == archived["sha256"] and
                          observation["control_plane_commit"] == archived["commit"] and
                          observation["status"] == "aws-test-recovery-root-preflight-complete" and
                          observation["compute_counts_by_type"] == {"t3.medium": 4}, "archived-inventory")
            end = prior.utc(args.cleanup_complete_by)
            result, components, fixed = report(profile, c, now, end)
            output = args.output_directory
            prior.private(output.parent, 0o700)
            prior.persistent(output)
            prior.require(not output.exists(), "new-output-directory-required")
            output.mkdir(mode=0o700)
            result["cost_profile_sha256"] = prior.digest(args.pricing)
            prior.write(output / "cost-review.json", result)
            if result["budget_model_fits"]:
                draft = prior.load(ROOT / "delivery/contracts/v0.11.9.3.6.7.5-private-plan.example.json")
                draft.update(control_plane_commit="__POST_MERGE_MAIN_SHA__",
                    observation_sha256="__FRESH_OBSERVATION_SHA256__", start_utc=prior.timestamp(),
                    cleanup_complete_by_utc=args.cleanup_complete_by,
                    hourly_upper_bound_usd={k: str(v) for k, v in components.items()},
                    fixed_and_uncertainty_reserve_usd=str(fixed),
                    pricing_reference="cost-profile-sha256:" + prior.digest(args.pricing),
                    estimate_covers_idle_and_post_root_peak=True,
                    estimate_covers_all_resources_not_only_tag_matches=True)
                prior.write(output / "private-plan-draft.json", draft)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["budget_model_fits"] else 1
        plan = read_private(args.plan)
        result = review_plan(plan, observation, profile, c, now, prior.digest(args.pricing),
                             args.expected_observation_sha256)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, InvalidOperation, KeyError, TypeError, OSError, OverflowError):
        parser.exit(1, "Stopped: cost inputs incomplete, stale, or invalid. Preserve evidence; no live operation.\n")


if __name__ == "__main__":
    sys.exit(main())
