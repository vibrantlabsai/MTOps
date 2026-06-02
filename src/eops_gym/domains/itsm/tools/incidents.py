"""Incident tools (14) — faithful port of the ITSM MCP's incident category.

Covers incident CRUD/search, priority/assignment-group aggregates, and the child-incident
relationship tools. Verified against the live MCP by the differential conformance test.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import ChildIncident, Incident
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool


class IncidentToolsMixin(ItsmToolsBase):
    """Incident management tools."""

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def create_incident(
        self,
        caller_id: str,
        short_description: str,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        impact: Optional[str] = None,
        urgency: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        worknotes: Optional[str] = None,
        resolution_notes: Optional[str] = None,
        close_notes: Optional[str] = None,
        resolution_code: Optional[str] = None,
        parent_incident: Optional[str] = None,
        problem: Optional[str] = None,
        change_request: Optional[str] = None,
        caused_by_change: Optional[str] = None,
        resolved_by: Optional[str] = None,
        on_hold_reason: Optional[str] = None,
        incident_template: Optional[str] = None,
        resolved: Optional[str] = None,
    ) -> Incident:
        """Create a new incident.

        Args:
            caller_id: User id of the person reporting the incident (required).
            short_description: Brief summary of the incident (required).
            service: Affected business service id.
            service_offering: Affected service offering id.
            configuration_item: Affected configuration item id.
            channel: Channel the incident came in on (email, phone, self-service).
            status: Incident status; defaults to 'new'.
            category: Incident category; defaults to 'inquiry-help'.
            description: Detailed description.
            impact: Business impact (high, medium, low); defaults to 'low'.
            urgency: Urgency (high, medium, low); defaults to 'low'.
            priority: Priority (critical, high, moderate, low, planning); defaults to 'planning'.
            assigned_to: Assignee user id.
            assignment_group: Assignment group id.
            worknotes: Internal work notes.
            resolution_notes: Resolution notes.
            close_notes: Closure notes.
            resolution_code: Resolution code.
            parent_incident: Parent incident id.
            problem: Related problem id.
            change_request: Related change id.
            caused_by_change: Change id that caused this incident.
            resolved_by: User id that resolved the incident.
            on_hold_reason: Reason if the incident is on hold.
            incident_template: Incident template id used.
            resolved: Resolution timestamp.

        Returns:
            The created incident.
        """
        self._require_user(caller_id, "caller_id")
        self._require_user(assigned_to, "assigned_to")
        self._require_user(resolved_by, "resolved_by")
        self._require_group(assignment_group)
        self._require_ci(configuration_item)

        incident_id, seq = self._make_id(self.db.incident, "INC")
        now = self._now()
        incident = Incident(
            incident_id=incident_id,
            number=f"INC-{seq:06d}",
            short_description=short_description,
            caller_id=caller_id,
            service=service,
            service_offering=service_offering,
            configuration_item=configuration_item,
            assigned_to=assigned_to,
            assignment_group=assignment_group,
            resolved_by=resolved_by,
            problem=problem,
            change_request=change_request,
            caused_by_change=caused_by_change,
            incident_template=incident_template,
            parent_incident=parent_incident,
            org_id=self._org_of_user(caller_id),
            channel=channel,
            contact_type=None,  # MCP does not derive contact_type on create (only seed has it)
            status=status or "new",
            category=category or "inquiry-help",
            description=description,
            worknotes=worknotes,
            resolution_notes=resolution_notes,
            close_notes=close_notes,
            impact=impact or "low",
            urgency=urgency or "low",
            priority=priority or "planning",
            resolution_code=resolution_code,
            on_hold_reason=on_hold_reason,
            resolved=resolved,
            created_at=now,
            updated_at=now,
        )
        self.db.incident[incident_id] = incident
        return incident

    @is_tool(ToolType.WRITE)
    def update_incident(
        self,
        incident_id: str,
        number: Optional[str] = None,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        caller_id: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        short_description: Optional[str] = None,
        description: Optional[str] = None,
        impact: Optional[str] = None,
        urgency: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        worknotes: Optional[str] = None,
        resolution_notes: Optional[str] = None,
        close_notes: Optional[str] = None,
        resolution_code: Optional[str] = None,
        parent_incident: Optional[str] = None,
        problem: Optional[str] = None,
        change_request: Optional[str] = None,
        caused_by_change: Optional[str] = None,
        resolved_by: Optional[str] = None,
        on_hold_reason: Optional[str] = None,
        incident_template: Optional[str] = None,
        resolved: Optional[str] = None,
    ) -> Incident:
        """Update an existing incident. Only the fields you pass are changed.

        Args:
            incident_id: Id of the incident to update (required).
            number: Incident number.
            service: Affected business service id.
            service_offering: Affected service offering id.
            configuration_item: Affected configuration item id.
            caller_id: Caller user id.
            channel: Channel (email, phone, self-service); also updates contact_type.
            status: Incident status.
            category: Incident category.
            short_description: Brief summary.
            description: Detailed description.
            impact: Business impact (high, medium, low).
            urgency: Urgency (high, medium, low).
            priority: Priority (critical, high, moderate, low, planning).
            assigned_to: Assignee user id.
            assignment_group: Assignment group id.
            worknotes: Internal work notes.
            resolution_notes: Resolution notes.
            close_notes: Closure notes.
            resolution_code: Resolution code.
            parent_incident: Parent incident id.
            problem: Related problem id.
            change_request: Related change id.
            caused_by_change: Change id that caused this incident.
            resolved_by: User id that resolved the incident.
            on_hold_reason: Reason if on hold.
            incident_template: Incident template id.
            resolved: Resolution timestamp.

        Returns:
            The updated incident.
        """
        incident = self._require_incident(incident_id)
        self._require_user(caller_id, "caller_id")
        self._require_user(assigned_to, "assigned_to")
        self._require_user(resolved_by, "resolved_by")
        self._require_group(assignment_group)
        self._require_ci(configuration_item)

        updates = {
            "number": number, "service": service, "service_offering": service_offering,
            "configuration_item": configuration_item, "caller_id": caller_id,
            "channel": channel, "status": status, "category": category,
            "short_description": short_description, "description": description,
            "impact": impact, "urgency": urgency, "priority": priority,
            "assigned_to": assigned_to, "assignment_group": assignment_group,
            "worknotes": worknotes, "resolution_notes": resolution_notes,
            "close_notes": close_notes, "resolution_code": resolution_code,
            "parent_incident": parent_incident, "problem": problem,
            "change_request": change_request, "caused_by_change": caused_by_change,
            "resolved_by": resolved_by, "on_hold_reason": on_hold_reason,
            "incident_template": incident_template, "resolved": resolved,
        }
        for field, value in updates.items():
            if value is not None:
                setattr(incident, field, value)
        incident.updated_at = self._now()
        return incident

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_incident_by_id(self, incident_id: str) -> Incident:
        """Return the incident with the given id.

        Args:
            incident_id: The incident id, e.g. 'INC_003'.

        Returns:
            The matching incident.
        """
        return self._require_incident(incident_id)

    @is_tool(ToolType.READ)
    def find_incident_by_number(self, number: str) -> Incident:
        """Return the incident with the given human-readable number.

        Args:
            number: The incident number, e.g. 'INC0000003'.

        Returns:
            The matching incident.
        """
        for inc in self.db.incident.values():
            if inc.number == number:
                return inc
        raise ItsmError(f"Incident with number '{number}' not found", field="number")

    @is_tool(ToolType.READ)
    def list_incidents(
        self,
        incident_id: Optional[str] = None,
        number: Optional[str] = None,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        called_id: Optional[str] = None,
        channel: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        short_description: Optional[str] = None,
        description: Optional[str] = None,
        impact: Optional[str] = None,
        urgency: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        worknotes: Optional[str] = None,
        resolution_notes: Optional[str] = None,
        close_notes: Optional[str] = None,
        resolution_code: Optional[str] = None,
        parent_incident: Optional[str] = None,
        problem: Optional[str] = None,
        change_request: Optional[str] = None,
        caused_by_change: Optional[str] = None,
        resolved_by: Optional[str] = None,
        on_hold_reason: Optional[str] = None,
        incident_template: Optional[str] = None,
        resolved: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> List[Incident]:
        """List incidents, optionally filtered. All filters are ANDed; omitted filters ignored.

        Args:
            incident_id: Filter by incident id.
            number: Filter by incident number.
            service: Filter by service id.
            service_offering: Filter by service offering id.
            configuration_item: Filter by configuration item id.
            called_id: Filter by caller user id.
            channel: Filter by channel.
            status: Filter by status.
            category: Filter by category.
            short_description: Filter by short description.
            description: Filter by description.
            impact: Filter by impact.
            urgency: Filter by urgency.
            priority: Filter by priority.
            assigned_to: Filter by assignee.
            assignment_group: Filter by assignment group.
            worknotes: Filter by work notes.
            resolution_notes: Filter by resolution notes.
            close_notes: Filter by close notes.
            resolution_code: Filter by resolution code.
            parent_incident: Filter by parent incident.
            problem: Filter by related problem.
            change_request: Filter by related change.
            caused_by_change: Filter by causing change.
            resolved_by: Filter by resolver.
            on_hold_reason: Filter by on-hold reason.
            incident_template: Filter by incident template.
            resolved: Filter by resolved timestamp.
            created_after: Only incidents created on/after this ISO timestamp.
            created_before: Only incidents created on/before this ISO timestamp.

        Returns:
            The list of matching incidents.
        """
        # map exposed filter name -> incident attribute ('called_id' is the MCP's spelling)
        eq_filters = {
            "incident_id": incident_id, "number": number, "service": service,
            "service_offering": service_offering, "configuration_item": configuration_item,
            "caller_id": called_id, "channel": channel, "status": status, "category": category,
            "short_description": short_description, "description": description, "impact": impact,
            "urgency": urgency, "priority": priority, "assigned_to": assigned_to,
            "assignment_group": assignment_group, "worknotes": worknotes,
            "resolution_notes": resolution_notes, "close_notes": close_notes,
            "resolution_code": resolution_code, "parent_incident": parent_incident,
            "problem": problem, "change_request": change_request,
            "caused_by_change": caused_by_change, "resolved_by": resolved_by,
            "on_hold_reason": on_hold_reason, "incident_template": incident_template,
            "resolved": resolved,
        }
        active = {k: v for k, v in eq_filters.items() if v is not None}
        out: List[Incident] = []
        for inc in self.db.incident.values():
            if any(getattr(inc, attr) != val for attr, val in active.items()):
                continue
            if created_after is not None and (inc.created_at or "") < created_after:
                continue
            if created_before is not None and (inc.created_at or "") > created_before:
                continue
            out.append(inc)
        return out

    @is_tool(ToolType.READ)
    def get_incidents_assigned_to(
        self, assignment_group: Optional[str] = None, assigned_to: Optional[str] = None
    ) -> List[Incident]:
        """List incidents assigned to a user and/or assignment group.

        Args:
            assignment_group: Assignment group id to filter by.
            assigned_to: Assignee user id to filter by.

        Returns:
            The list of matching incidents.
        """
        out: List[Incident] = []
        for inc in self.db.incident.values():
            if assignment_group is not None and inc.assignment_group != assignment_group:
                continue
            if assigned_to is not None and inc.assigned_to != assigned_to:
                continue
            out.append(inc)
        return out

    @is_tool(ToolType.READ)
    def get_count_of_incident_priority_wise(self, priority_list: List[str]) -> dict:
        """Count incidents for each priority in the given list.

        Args:
            priority_list: Priorities to count, e.g. ['high', 'critical'].

        Returns:
            A mapping of each requested priority to its incident count.
        """
        counts = {p: 0 for p in priority_list}
        for inc in self.db.incident.values():
            if inc.priority in counts:
                counts[inc.priority] += 1
        return counts

    @is_tool(ToolType.READ)
    def count_incident_for_assignment_group(
        self,
        assignment_group_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict:
        """Count incidents for an assignment group, optionally filtered.

        Args:
            assignment_group_id: The assignment group id.
            status: Optional status filter.
            priority: Optional priority filter.
            channel: Optional channel filter.

        Returns:
            A mapping of the group id to the matching incident count.
        """
        count = 0
        for inc in self.db.incident.values():
            if inc.assignment_group != assignment_group_id:
                continue
            if status is not None and inc.status != status:
                continue
            if priority is not None and inc.priority != priority:
                continue
            if channel is not None and inc.channel != channel:
                continue
            count += 1
        return {assignment_group_id: count}

    # --------------------------------------------------------- child incidents
    def _add_child(self, parent_incident: str, child_incident: str) -> ChildIncident:
        self._require_incident(parent_incident, "parent_incident")
        self._require_incident(child_incident, "child_incident")
        if parent_incident == child_incident:
            raise ItsmError(
                "An incident cannot be its own child", code="INVALID_RELATIONSHIP",
                field="child_incident",
            )
        for m in self.db.child_incident.values():
            if m.parent_incident == parent_incident and m.child_incident == child_incident:
                raise ItsmError(
                    f"Child incident relationship already exists: '{parent_incident}' -> "
                    f"'{child_incident}'", code="INVALID_RELATIONSHIP", field="child_incident",
                )
        mapping_id, _ = self._make_id(self.db.child_incident, "CINC")
        now = self._now()
        mapping = ChildIncident(
            child_incident_mapping_id=mapping_id,
            parent_incident=parent_incident,
            child_incident=child_incident,
            created_at=now,
            updated_at=now,
        )
        self.db.child_incident[mapping_id] = mapping
        return mapping

    @is_tool(ToolType.WRITE)
    def add_child_incident(self, parent_incident: str, child_incident: str) -> ChildIncident:
        """Link a child incident to a parent incident.

        Args:
            parent_incident: The parent incident id.
            child_incident: The child incident id.

        Returns:
            The created parent-child mapping.
        """
        return self._add_child(parent_incident, child_incident)

    @is_tool(ToolType.WRITE)
    def add_child_incidents(
        self, parent_incident: str, child_incidents: List[str]
    ) -> List[ChildIncident]:
        """Link multiple child incidents to a parent incident.

        Args:
            parent_incident: The parent incident id.
            child_incidents: The child incident ids to link.

        Returns:
            The created parent-child mappings.
        """
        return [self._add_child(parent_incident, child) for child in child_incidents]

    @is_tool(ToolType.WRITE)
    def update_child_incident(
        self, child_incident_mapping_id: str, parent_incident: str, child_incident: str
    ) -> ChildIncident:
        """Update an existing parent-child incident mapping.

        Args:
            child_incident_mapping_id: The mapping id to update.
            parent_incident: The new parent incident id.
            child_incident: The new child incident id.

        Returns:
            The updated mapping.
        """
        mapping = self.db.child_incident.get(child_incident_mapping_id)
        if mapping is None:
            raise ItsmError(
                f"Child incident mapping '{child_incident_mapping_id}' not found",
                field="child_incident_mapping_id",
            )
        self._require_incident(parent_incident, "parent_incident")
        self._require_incident(child_incident, "child_incident")
        mapping.parent_incident = parent_incident
        mapping.child_incident = child_incident
        mapping.updated_at = self._now()
        return mapping

    @is_tool(ToolType.WRITE)
    def remove_child_incident(
        self,
        child_incident_mapping_id: Optional[str] = None,
        parent_incident: Optional[str] = None,
        child_incident: Optional[str] = None,
    ) -> dict:
        """Remove parent-child incident mapping(s) matching the given filters.

        Args:
            child_incident_mapping_id: Remove the mapping with this id.
            parent_incident: Remove mappings with this parent.
            child_incident: Remove mappings with this child.

        Returns:
            A summary with the number of mappings removed.
        """
        to_remove = []
        for mid, m in self.db.child_incident.items():
            if child_incident_mapping_id is not None and mid != child_incident_mapping_id:
                continue
            if parent_incident is not None and m.parent_incident != parent_incident:
                continue
            if child_incident is not None and m.child_incident != child_incident:
                continue
            to_remove.append(mid)
        for mid in to_remove:
            del self.db.child_incident[mid]
        return {"success": True, "deleted_count": len(to_remove)}

    @is_tool(ToolType.READ)
    def list_child_incidents(self, parent_incident: str) -> List[ChildIncident]:
        """List the child-incident mappings for a parent incident.

        Args:
            parent_incident: The parent incident id.

        Returns:
            The child-incident mappings.
        """
        return [m for m in self.db.child_incident.values()
                if m.parent_incident == parent_incident]

    @is_tool(ToolType.READ)
    def find_parent_incident(self, child_incident: str) -> ChildIncident:
        """Find the parent-child mapping for a child incident.

        Args:
            child_incident: The child incident id.

        Returns:
            The mapping whose child is the given incident.
        """
        for m in self.db.child_incident.values():
            if m.child_incident == child_incident:
                return m
        raise ItsmError(
            f"No parent found for child incident '{child_incident}'", field="child_incident"
        )
