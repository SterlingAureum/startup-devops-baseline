#!/usr/bin/env python3
"""Command-free plan, state, dependency, and history gates for two-wave teardown."""

from __future__ import annotations

import re
from typing import Any, Iterable


NETWORK_ADDRESS_PREFIX = "module.vpc."
SUPPORTED_ENVIRONMENTS = ("aws-dev", "aws-test")
ENVIRONMENT_PROFILES = {
    "aws-dev": {
        "shortName": "dev",
        "stateKey": "environments/dev/terraform.tfstate",
        "applicationBackupDeletionAllowed": True,
        "remoteStateActivationRequired": False,
    },
    "aws-test": {
        "shortName": "test",
        "stateKey": "environments/test/terraform.tfstate",
        "applicationBackupDeletionAllowed": True,
        "remoteStateActivationRequired": True,
    },
}
INVENTORY_FAMILIES = (
    "eks-cluster",
    "instances-and-karpenter-fleets",
    "load-balancers-and-target-groups",
    "nat-and-internet-gateways",
    "vpc-endpoints-and-peering",
    "transit-and-vpn-attachments",
    "network-interfaces",
    "security-groups-and-references",
    "ebs-volumes",
    "subnets-route-tables-and-network-acls",
    "application-backup-bucket",
    "terraform-state-and-lock-history",
)
SAFE_RESIDUE_CATEGORIES = {
    "detached-dynamic-pvc-volume",
    "orphan-kubernetes-eni",
    "orphan-eks-cluster-security-group",
}
HISTORY_KEYS = {
    "stateVersions",
    "stateDeleteMarkers",
    "lockVersions",
    "lockDeleteMarkers",
    "lockLatestVersions",
    "lockLatestDeleteMarkers",
}


class TeardownGateError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TeardownGateError(message)


def environment_profile(environment: str) -> dict[str, Any]:
    require(environment in SUPPORTED_ENVIRONMENTS, "Live teardown profile must be aws-dev or aws-test")
    return dict(ENVIRONMENT_PROFILES[environment])


def normalized_addresses(addresses: Iterable[str]) -> tuple[str, ...]:
    values = tuple(addresses)
    require(values and all(isinstance(value, str) and value.strip() == value and value for value in values), "Managed address inventory is empty or malformed")
    require(len(set(values)) == len(values), "Managed address inventory contains duplicates")
    return tuple(sorted(values))


def is_network_address(address: str) -> bool:
    return address.startswith(NETWORK_ADDRESS_PREFIX)


def partition_managed_addresses(addresses: Iterable[str]) -> dict[str, list[str]]:
    values = normalized_addresses(addresses)
    network = sorted(value for value in values if is_network_address(value))
    non_network = sorted(value for value in values if not is_network_address(value))
    require(network, "Two-wave teardown requires a retained network shell")
    require(non_network, "Two-wave teardown requires non-network first-wave addresses")
    return {"networkAddresses": network, "nonNetworkAddresses": non_network}


def _plan_inventory(document: dict[str, Any]) -> dict[str, Any]:
    require(document.get("complete") is True and document.get("errored") is False and document.get("applyable") is True, "Saved plan is not complete and applyable")
    drift = document.get("resource_drift", [])
    require(isinstance(drift, list) and not drift, "Saved plan contains resource drift")
    changes = document.get("resource_changes")
    require(isinstance(changes, list) and changes, "Saved plan has no resource changes")
    managed: set[str] = set()
    data: set[str] = set()
    for item in changes:
        require(isinstance(item, dict) and isinstance(item.get("address"), str), "Plan resource change shape changed")
        change = item.get("change")
        require(isinstance(change, dict) and isinstance(change.get("actions"), list), "Plan action shape changed")
        require(change.get("importing") is None, "Saved plan contains import")
        if item.get("mode") == "managed":
            require(change["actions"] == ["delete"], f"Managed action is not delete-only: {item['address']}")
            require(item["address"] not in managed, "Saved plan repeats a managed address")
            managed.add(item["address"])
        elif item.get("mode") == "data":
            require(change["actions"] in (["read"], ["no-op"], ["delete"]), f"Data action changed: {item['address']}")
            data.add(item["address"])
        else:
            raise TeardownGateError(f"Unsupported resource mode: {item.get('mode')}")
    outputs = document.get("output_changes", {})
    require(isinstance(outputs, dict), "Plan output changes shape changed")
    require(all(isinstance(value, dict) and value.get("actions") in (["delete"], ["no-op"]) for value in outputs.values()), "Plan output action changed")
    return {
        "managedDeleteAddresses": sorted(managed),
        "dataChangeAddresses": sorted(data),
        "managedDeleteCount": len(managed),
        "dataChangeCount": len(data),
        "resourceDriftCount": 0,
        "importCount": 0,
    }


def gate_wave_one_plan(document: dict[str, Any], prior_managed_addresses: Iterable[str]) -> dict[str, Any]:
    partition = partition_managed_addresses(prior_managed_addresses)
    inventory = _plan_inventory(document)
    require(inventory["managedDeleteAddresses"] == partition["nonNetworkAddresses"], "Wave-one plan must delete all and only non-network addresses")
    inventory["wave"] = "non-network"
    inventory["retainedNetworkAddresses"] = partition["networkAddresses"]
    return inventory


def gate_post_wave_one_state(prior_managed_addresses: Iterable[str], current_managed_addresses: Iterable[str]) -> dict[str, Any]:
    partition = partition_managed_addresses(prior_managed_addresses)
    current = list(normalized_addresses(current_managed_addresses))
    require(current == partition["networkAddresses"], "Post-wave-one state must equal the prior network shell")
    return {"remainingManagedAddresses": current, "remainingManagedCount": len(current), "nonNetworkManagedCount": 0}


def gate_dependency_inventory(document: dict[str, Any], expected_environment: str, expected_network_count: int) -> dict[str, Any]:
    environment_profile(expected_environment)
    require(document.get("environment") == expected_environment, "Dependency inventory environment changed")
    require(document.get("eksAbsent") is True, "EKS must be absent before VPC dependency classification")
    require(document.get("managedNetworkAddressCount") == expected_network_count and expected_network_count > 0, "Managed network count changed")
    require(document.get("controllerOwnedDependencyCount") == 0, "Controller-owned dependencies remain")
    require(document.get("unknownDependencyCount") == 0, "Unknown dependencies fail closed")
    families = document.get("inventoryFamilies")
    require(isinstance(families, list) and tuple(families) == INVENTORY_FAMILIES, "Dependency inventory families changed")
    foundation = document.get("protectedFoundation")
    require(isinstance(foundation, dict), "Protected foundation inventory missing")
    require(foundation == {"stateBackendPreserved": True, "runtimeIdentitiesPreserved": True}, "Protected foundation boundary changed")
    residues = document.get("safeResidues")
    require(isinstance(residues, list), "Safe residue inventory changed")
    seen: set[str] = set()
    for residue in residues:
        require(isinstance(residue, dict) and set(residue) == {"category", "identitySha256", "exactBound", "deletionAuthorized"}, "Safe residue shape changed")
        require(residue["category"] in SAFE_RESIDUE_CATEGORIES, "Unrecognized safe residue category")
        require(isinstance(residue["identitySha256"], str) and re.fullmatch(r"[0-9a-f]{64}", residue["identitySha256"]) is not None, "Safe residue identity must be SHA-256 only")
        require(residue["identitySha256"] not in seen, "Safe residue identity repeated")
        require(residue["exactBound"] is True and residue["deletionAuthorized"] is False, "Inventory cannot authorize safe-residue deletion")
        seen.add(residue["identitySha256"])
    return {"safeResidueCount": len(residues), "separateCleanupApprovalRequired": bool(residues), "waveTwoEligible": not residues}


def gate_wave_two_plan(document: dict[str, Any], remaining_managed_addresses: Iterable[str], dependency_result: dict[str, Any]) -> dict[str, Any]:
    remaining = list(normalized_addresses(remaining_managed_addresses))
    require(all(is_network_address(address) for address in remaining), "Wave-two input contains non-network addresses")
    require(dependency_result == {"safeResidueCount": 0, "separateCleanupApprovalRequired": False, "waveTwoEligible": True}, "Wave-two requires a clean post-cluster dependency inventory")
    inventory = _plan_inventory(document)
    require(inventory["managedDeleteAddresses"] == remaining, "Wave-two plan must delete all and only remaining network addresses")
    inventory["wave"] = "network"
    return inventory


def _history(value: dict[str, Any]) -> dict[str, int]:
    require(isinstance(value, dict) and set(value) == HISTORY_KEYS, "History counter shape changed")
    require(all(isinstance(item, int) and not isinstance(item, bool) and item >= 0 for item in value.values()), "History counters must be nonnegative integers")
    return value


def gate_history_delta(before: dict[str, Any], after: dict[str, Any], *, state_write_expected: bool) -> dict[str, int]:
    old = _history(before)
    new = _history(after)
    expected_state_delta = 1 if state_write_expected else 0
    require(new["stateVersions"] - old["stateVersions"] == expected_state_delta, "Canonical state version delta changed")
    require(new["stateDeleteMarkers"] - old["stateDeleteMarkers"] == 0, "Canonical state gained a delete marker")
    require(new["lockVersions"] - old["lockVersions"] == 1, "Lock version delta changed")
    require(new["lockDeleteMarkers"] - old["lockDeleteMarkers"] == 1, "Lock delete-marker delta changed")
    require(new["lockLatestVersions"] == 0 and new["lockLatestDeleteMarkers"] == 1, "Terraform native lock is not cleanly released")
    return {
        "stateObjectVersionDelta": expected_state_delta,
        "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1,
        "lockDeleteMarkerDelta": 1,
        "lockLatestVersionCount": 0,
        "lockLatestDeleteMarkerCount": 1,
    }


def gate_final_state(managed_addresses: Iterable[str]) -> dict[str, Any]:
    values = tuple(managed_addresses)
    require(not values, "Final managed state must be empty")
    return {"managedStateAddressCount": 0, "finalManagedStateEmpty": True}
