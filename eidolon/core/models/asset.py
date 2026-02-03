from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from eidolon.core.models.graph import Node


class Asset(Node):
    """Infrastructure asset node."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    label: str = Field(default="Asset")
    kind: str = Field(
        default="host",
        description="Type of asset (host, vm, router, firewall, service, db, saas, etc.)",
    )
    env: str | None = Field(default=None, description="Environment tag (prod, staging, dev, etc.)")
    criticality: str | None = Field(default=None, description="Business impact rating")
    owner_team: str | None = Field(default=None)
    lifecycle_state: str | None = Field(
        default=None, description="active, deprecated, retired, etc."
    )
    identifiers: list[str] = Field(
        default_factory=list, description="Hostnames, IPs, MACs, instance IDs"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class NetworkContainer(Node):
    """Network container such as VPC, subnet, VLAN, or security zone."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    label: str = Field(default="NetworkContainer")
    cidr: str = Field(description="CIDR range for the network container")
    name: str | None = Field(default=None)
    network_type: str | None = Field(
        default=None, description="VPC, subnet, vlan, segment, zone, etc."
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class Identity(Node):
    """Identity representation for users, service accounts, or groups."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    label: str = Field(default="Identity")
    identity_type: str = Field(
        default="user", description="user, service_account, role, group, etc."
    )
    name: str = Field(description="Canonical identity name")
    groups: list[str] = Field(default_factory=list)
    privileges: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Policy(Node):
    """Policy node capturing access/change rules."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    label: str = Field(default="Policy")
    policy_type: str = Field(default="access")
    description: str | None = Field(default=None)
    rules: dict[str, Any] = Field(default_factory=dict)


class Tool(Node):
    """Execution tool representation."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    label: str = Field(default="Tool")
    name: str = Field(description="Tool name (ansible, terraform, ssm, etc.)")
    version: str | None = Field(default=None)
    sandbox_execution: bool = Field(default=True)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Capability(Node):
    """Capability required by actions (ssh, winrm, api-scope)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    label: str = Field(default="Capability")
    name: str = Field(description="Capability identifier")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionType(Node):
    """Action type that tools implement (run_command, change_firewall_rule)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    label: str = Field(default="ActionType")
    name: str = Field(description="Action name")
    description: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSource(Node):
    """Evidence source metadata."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    label: str = Field(default="EvidenceSource")
    source_type: str = Field(description="flow_logs, snmp, lldp, cloud_api, iam_export, etc.")
    reference: str | None = Field(default=None, description="Opaque reference to the source record")
    metadata: dict[str, Any] = Field(default_factory=dict)
