#!/usr/bin/env python3
"""Offline regressions for elapsed-time, capacity and incomplete-price failure boundaries."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cost", ROOT / "scripts/review-v0.11.9.3.6.7.5.1-aws-test-root-cost.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CostTests(unittest.TestCase):
    def setUp(self):
        self.c = m.source_checks()
        self.now = datetime(2026, 9, 13, 1, 40, tzinfo=timezone.utc)
        self.p = m.prior.load(ROOT / "delivery/contracts/v0.11.9.3.6.7.5.1-cost-profile.example.json")
        # Synthetic rates exercise arithmetic. These are not market prices.
        for group in (self.p["rates"], self.p["pool_node_hourly_upper_usd"]):
            for item in group.values():
                item.update(usd="0.01", reference="synthetic offline arithmetic fixture",
                            reviewed_at_utc="2026-09-13T01:39:00Z",
                            coverage_note="synthetic all-resource coverage fixture")
        self.p["rates"]["eks_hourly"]["usd"] = "0.10"
        self.p["rates"]["ebs_gib_hourly"]["usd"] = "0.0001"
        self.p["fixed_and_uncertainty_reserve_usd"] = "0.50"
        self.p["all_eligible_instance_types_and_spot_fallback_reviewed"] = True
        self.p["all_ebs_snapshots_backups_transfer_and_lcu_reviewed"] = True

    def test_full_capacity_includes_all_pools_and_overshoot(self):
        _, _, capacity = m.estimate(self.p, self.c, self.now)
        self.assertEqual(capacity["configured_additional_node_limit_sum"], 10)
        self.assertEqual(capacity["additional_node_estimate_with_overshoot"], 11)
        self.assertEqual(capacity["estimated_ebs_gib"], 522)
        self.assertFalse(capacity["configured_limits_are_billing_hard_caps"])

    def test_incomplete_prices_stop(self):
        self.p["rates"]["transfer_hourly"]["usd"] = None
        with self.assertRaises(ValueError):
            m.estimate(self.p, self.c, self.now)

    def test_nonfinite_negative_and_number_prices_stop(self):
        for value in ("NaN", "Infinity", "-0.1", 0.1):
            with self.subTest(value=value):
                self.p["rates"]["eks_hourly"]["usd"] = value
                with self.assertRaises(ValueError):
                    m.estimate(self.p, self.c, self.now)

    def test_unused_pool_cannot_be_omitted(self):
        self.p["pool_node_hourly_upper_usd"].pop("application-spot-fis")
        with self.assertRaises(ValueError):
            m.estimate(self.p, self.c, self.now)

    def test_overshoot_cannot_be_zero_or_boolean(self):
        for value in (0, True):
            self.p["overshoot_node_reserve"] = value
            with self.assertRaises(ValueError):
                m.estimate(self.p, self.c, self.now)

    def test_nat_alb_ipv4_reserve(self):
        self.p["public_ipv4_count_upper"] = 1
        with self.assertRaises(ValueError):
            m.estimate(self.p, self.c, self.now)

    def test_price_ttl_and_future_review(self):
        for timestamp in ("2026-09-11T01:39:00Z", "2026-09-13T01:41:00Z"):
            self.p["rates"]["eks_hourly"]["reviewed_at_utc"] = timestamp
            with self.assertRaises(ValueError):
                m.estimate(self.p, self.c, self.now)

    def test_elapsed_peak_cost_is_included(self):
        end = m.prior.utc("2026-09-13T04:00:00Z")
        result, components, fixed = m.report(self.p, self.c, self.now, end)
        self.assertTrue(result["budget_model_fits"])
        self.assertGreater(m.prior.amount(result["elapsed_peak_cost_estimate_usd"]), 0)
        total = sum(components.values()) * m.Decimal(str((end - m.prior.utc(self.c["accountingStartUtc"])).total_seconds())) / 3600 + fixed
        self.assertGreaterEqual(m.prior.amount(result["estimated_additional_cost_through_cleanup_usd"]), total)
        self.assertIsNone(result["historical_spend_usd"])
        self.assertFalse(result["root_deployment_authorized"])

    def test_window_does_not_reset_accounting_anchor(self):
        self.p["rates"]["extra_ec2_hourly"]["usd"] = "4.00"
        result, _, _ = m.report(self.p, self.c, self.now, m.prior.utc("2026-09-13T03:20:00Z"))
        self.assertFalse(result["budget_model_fits"])
        self.assertLess(m.prior.utc(result["latest_cleanup_complete_by_utc"]), m.prior.utc("2026-09-13T03:20:00Z"))

    def test_short_cleanup_or_operator_unavailable_stops(self):
        for end in ("2026-09-13T02:00:00Z", "2026-09-13T13:00:00Z"):
            result, _, _ = m.report(self.p, self.c, self.now, m.prior.utc(end))
            self.assertFalse(result["budget_model_fits"])

    def test_coverage_confirmation_required(self):
        self.p["all_eligible_instance_types_and_spot_fallback_reviewed"] = False
        with self.assertRaises(ValueError):
            m.estimate(self.p, self.c, self.now)

    def test_fixed_reserve_mandatory(self):
        self.p["fixed_and_uncertainty_reserve_usd"] = "0"
        with self.assertRaises(ValueError):
            m.estimate(self.p, self.c, self.now)

    def test_published_price_floor(self):
        self.p["rates"]["eks_hourly"]["usd"] = "0.01"
        with self.assertRaises(ValueError):
            m.estimate(self.p, self.c, self.now)

    def test_template_is_not_a_price_estimate(self):
        example = m.prior.load(ROOT / "delivery/contracts/v0.11.9.3.6.7.5.1-cost-profile.example.json")
        with self.assertRaises(ValueError):
            m.estimate(example, self.c, self.now)

    def fresh_plan(self):
        components, fixed, _ = m.estimate(self.p, self.c, self.now)
        plan = m.prior.load(ROOT / "delivery/contracts/v0.11.9.3.6.7.5-private-plan.example.json")
        plan.update(control_plane_commit="a" * 40, observation_sha256="b" * 64,
                    start_utc="2026-09-13T01:41:00Z", cleanup_complete_by_utc="2026-09-13T04:00:00Z",
                    hourly_upper_bound_usd={k: str(v) for k, v in components.items()},
                    fixed_and_uncertainty_reserve_usd=str(fixed),
                    pricing_reference="cost-profile-sha256:" + "c" * 64,
                    estimate_covers_idle_and_post_root_peak=True,
                    estimate_covers_all_resources_not_only_tag_matches=True)
        plan["reviewed_scope"] = {k: True for k in m.prior.SCOPES}
        observation = {"status": "aws-test-recovery-root-preflight-complete",
                       "control_plane_commit": "a" * 40, "observed_at_utc": "2026-09-13T01:39:00Z"}
        return plan, observation

    def test_successor_review_keeps_authorization_false(self):
        plan, observation = self.fresh_plan()
        result = m.review_plan(plan, observation, self.p, self.c, self.now, "c" * 64, "b" * 64)
        self.assertFalse(result["root_deployment_authorized"])
        self.assertEqual(result["cost_profile_sha256"], "c" * 64)

    def test_understated_ec2_or_ebs_cannot_pass_successor(self):
        for component in ("ec2", "ebs"):
            plan, observation = self.fresh_plan()
            plan["hourly_upper_bound_usd"][component] = "0"
            with self.assertRaises(ValueError):
                m.review_plan(plan, observation, self.p, self.c, self.now, "c" * 64, "b" * 64)

    def test_changed_profile_and_stale_preflight_stop_successor(self):
        plan, observation = self.fresh_plan()
        with self.assertRaises(ValueError):
            m.review_plan(plan, observation, self.p, self.c, self.now, "d" * 64, "b" * 64)
        observation["observed_at_utc"] = "2026-09-13T01:24:43Z"
        with self.assertRaises(ValueError):
            m.review_plan(plan, observation, self.p, self.c, self.now, "c" * 64, "b" * 64)

    def test_design_cannot_set_mutation_approval(self):
        plan, observation = self.fresh_plan()
        plan["root_deployment_authorized"] = True
        with self.assertRaises(ValueError):
            m.review_plan(plan, observation, self.p, self.c, self.now, "c" * 64, "b" * 64)


if __name__ == "__main__":
    unittest.main()
