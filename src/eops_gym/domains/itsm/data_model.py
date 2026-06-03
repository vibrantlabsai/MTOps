"""ITSM domain data model — faithful port of the ServiceNow ITSM MCP schema.

Every model mirrors a table in the authoritative DDL (``docs/itsm_schema.sql``, dumped from the
live MCP). Field names/order match the DDL exactly; ``extra="forbid"`` makes loading a ported
``db.json`` an exact-schema gate. Enum-like columns are typed ``str`` (not ``Literal``) so the
seed db loads; allowed values are documented in ``docs/itsm_build_spec.md``.

Per-table timestamp column names intentionally differ (``incident`` uses created_at/updated_at;
most others created_on/updated_on) — preserved verbatim for DB-hash fidelity.
"""

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from eops_gym.environment.db import DB


class ItsmRecord(BaseModel):
    """Base for all ITSM records: forbid unknown fields to catch schema drift."""

    model_config = ConfigDict(extra="forbid")


class Organization(ItsmRecord):
    org_id: str
    name: str
    active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Role(ItsmRecord):
    role_id: str
    name: str


class Permission(ItsmRecord):
    perm_id: str
    resource: str
    action: str


class RolePermission(ItsmRecord):
    role_id: str
    perm_id: str


class Location(ItsmRecord):
    location_id: str
    name: str
    org_id: str
    plot_no: Optional[str] = None
    street: Optional[str] = None
    city: str
    state: Optional[str] = None
    country: str
    active: bool
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class User(ItsmRecord):
    user_id: str
    user_name: str
    first_name: str
    last_name: str
    email: str
    phone: str
    role: str
    active: bool
    static_token: str
    org_id: str
    location_id: Optional[str] = None
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class UserRole(ItsmRecord):
    user_id: str
    role_id: str
    org_id: str


class UserGroup(ItsmRecord):
    group_id: str
    name: str
    type: str
    active: bool
    email: Optional[str] = None
    description: Optional[str] = None
    manager_id: str
    org_id: str
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class UserGroupMember(ItsmRecord):
    member_id: str
    group_id: str
    user_id: str
    org_id: str
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class Service(ItsmRecord):
    service_id: str
    name: str
    owned_by: str
    org_id: str
    used_for: str
    status: str
    service_classification: str
    business_criticality: str
    description: Optional[str] = None
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class ServiceOffering(ItsmRecord):
    service_offering_id: str
    name: str
    short_description: str
    owned_by: str
    business_service: str
    org_id: str
    used_for: str
    status: str
    service_classification: str
    business_criticality: str
    description: Optional[str] = None
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class ConfigurationItem(ItsmRecord):
    configuration_item_id: str
    name: str
    serial_number: str
    owner_id: str
    location_id: Optional[str] = None
    org_id: str
    status: str
    cost: Optional[float] = None
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class IncidentTemplate(ItsmRecord):
    incident_template_id: str
    name: str
    active: Optional[bool] = None
    caller_id: str
    channel: Optional[str] = None
    short_description: str
    category: Optional[str] = None
    impact: str
    urgency: str
    priority: str
    configuration_item: Optional[str] = None
    service: Optional[str] = None
    service_offering: Optional[str] = None
    org_id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Incident(ItsmRecord):
    incident_id: str
    number: str
    short_description: str
    caller_id: str
    service: Optional[str] = None
    service_offering: Optional[str] = None
    configuration_item: Optional[str] = None
    assigned_to: Optional[str] = None
    assignment_group: Optional[str] = None
    resolved_by: Optional[str] = None
    problem: Optional[str] = None
    change_request: Optional[str] = None
    caused_by_change: Optional[str] = None
    incident_template: Optional[str] = None
    parent_incident: Optional[str] = None
    org_id: str
    channel: Optional[str] = None
    contact_type: Optional[str] = None
    status: str
    category: str
    description: Optional[str] = None
    worknotes: Optional[str] = None
    resolution_notes: Optional[str] = None
    close_notes: Optional[str] = None
    impact: str
    urgency: str
    priority: str
    resolution_code: Optional[str] = None
    on_hold_reason: Optional[str] = None
    resolved: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    service_display: Optional[str] = None
    service_offering_display: Optional[str] = None
    configuration_item_display: Optional[str] = None
    assigned_to_display: Optional[str] = None
    assignment_group_display: Optional[str] = None
    parent_incident_display: Optional[str] = None
    problem_display: Optional[str] = None
    change_request_display: Optional[str] = None
    incident_template_display: Optional[str] = None


class ChildIncident(ItsmRecord):
    child_incident_mapping_id: str
    parent_incident: str
    child_incident: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Problem(ItsmRecord):
    problem_id: str
    number: str
    problem_statement: str
    short_description: Optional[str] = None
    opened_by: str
    service: Optional[str] = None
    service_offering: Optional[str] = None
    configuration_item: Optional[str] = None
    assigned_to: Optional[str] = None
    assignment_group: Optional[str] = None
    original_task: Optional[str] = None
    org_id: str
    status: str
    category: Optional[str] = None
    worknotes: Optional[str] = None
    workaround: Optional[str] = None
    fix_notes: Optional[str] = None
    impact: str
    urgency: str
    priority: str
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class Change(ItsmRecord):
    change_id: str
    number: str
    short_description: str
    requested_by: str
    service: Optional[str] = None
    service_offering: Optional[str] = None
    configuration_item: Optional[str] = None
    assigned_to: Optional[str] = None
    assignment_group: Optional[str] = None
    org_id: str
    status: str
    category: str
    description: Optional[str] = None
    implementation_plan: Optional[str] = None
    testing_plan: Optional[str] = None
    close_notes: Optional[str] = None
    cab_required: Optional[bool] = None
    impact: str
    priority: str
    risk: str
    close_code: Optional[str] = None
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class ChangeRequestMapping(ItsmRecord):
    change_request_mapping_id: str
    change_id: str
    incident_id: Optional[str] = None
    problem_id: Optional[str] = None
    org_id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Knowledge(ItsmRecord):
    knowledge_id: str
    kb_number: str
    title: str
    short_description: Optional[str] = None
    body: Optional[str] = None
    state: str
    visibility: str
    owner_id: Optional[str] = None
    org_id: str
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class IncidentKnowledge(ItsmRecord):
    incident_kb_id: str
    incident_id: str
    knowledge_id: str
    org_id: str
    used_as: str
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class IncidentAffectedCI(ItsmRecord):
    incident_affected_cis_id: str
    configuration_item: str
    incident_id: str
    org_id: str
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class SLADefinition(ItsmRecord):
    sla_def_id: str
    name: str
    metric: str
    target_mins: int
    pause_on_pending: bool
    applies_to_priority: Optional[str] = None
    active: bool
    schedule: Optional[str] = None
    org_id: str
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class IncidentSLA(ItsmRecord):
    incident_sla_id: str
    incident_id: str
    sla_def_id: str
    org_id: str
    stage: str
    has_breached: bool
    start_time: str
    breach_time: Optional[str] = None
    completed_time: Optional[str] = None
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class Notification(ItsmRecord):
    notification_id: str
    incident_id: str
    org_id: str
    email: str
    subject: Optional[str] = None
    message: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    created_on: Optional[str] = None
    updated_on: Optional[str] = None


class ItsmDB(DB):
    """In-memory ITSM database. One collection per table, keyed by primary key.

    Composite-key tables (role_permission, user_role) are keyed by their PK columns joined
    with ':' by the seed porter; the record still carries the individual columns.
    """

    organization: Dict[str, Organization] = Field(default_factory=dict)
    role: Dict[str, Role] = Field(default_factory=dict)
    permission: Dict[str, Permission] = Field(default_factory=dict)
    role_permission: Dict[str, RolePermission] = Field(default_factory=dict)
    location: Dict[str, Location] = Field(default_factory=dict)
    users: Dict[str, User] = Field(default_factory=dict)
    user_role: Dict[str, UserRole] = Field(default_factory=dict)
    user_group: Dict[str, UserGroup] = Field(default_factory=dict)
    user_group_member: Dict[str, UserGroupMember] = Field(default_factory=dict)
    service: Dict[str, Service] = Field(default_factory=dict)
    service_offering: Dict[str, ServiceOffering] = Field(default_factory=dict)
    configuration_item: Dict[str, ConfigurationItem] = Field(default_factory=dict)
    incident_template: Dict[str, IncidentTemplate] = Field(default_factory=dict)
    incident: Dict[str, Incident] = Field(default_factory=dict)
    child_incident: Dict[str, ChildIncident] = Field(default_factory=dict)
    problem: Dict[str, Problem] = Field(default_factory=dict)
    change: Dict[str, Change] = Field(default_factory=dict)
    change_request_mapping: Dict[str, ChangeRequestMapping] = Field(default_factory=dict)
    knowledge: Dict[str, Knowledge] = Field(default_factory=dict)
    incident_knowledge: Dict[str, IncidentKnowledge] = Field(default_factory=dict)
    incident_affected_cis: Dict[str, IncidentAffectedCI] = Field(default_factory=dict)
    sla_definition: Dict[str, SLADefinition] = Field(default_factory=dict)
    incident_sla: Dict[str, IncidentSLA] = Field(default_factory=dict)
    notification: Dict[str, Notification] = Field(default_factory=dict)
