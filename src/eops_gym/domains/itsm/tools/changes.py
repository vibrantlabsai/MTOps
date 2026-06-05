"""Change tools (5) — faithful port of the ITSM MCP's change category.

Covers change-request CRUD/search and assignment lookups.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import Change
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool

# list_changes filter fields that match as case-insensitive substrings (per the catalog).
_PARTIAL_MATCH_FIELDS = (
    "short_description", "description", "implementation_plan", "testing_plan", "close_notes",
)


class ChangeToolsMixin(ItsmToolsBase):
    """Change management tools."""

    # ------------------------------------------------------------------ helpers
    def _chg_require_service(self, service_id: Optional[str], field: str = "service") -> None:
        if service_id is not None and service_id not in self.db.service:
            raise ItsmError(
                f"Service with ID '{service_id}' not found",
                code="INVALID_REFERENCE", field=field,
            )

    def _chg_require_service_offering(
        self, service_offering_id: Optional[str], field: str = "service_offering"
    ) -> None:
        if service_offering_id is not None and service_offering_id not in self.db.service_offering:
            raise ItsmError(
                f"Service offering with ID '{service_offering_id}' not found",
                code="INVALID_REFERENCE", field=field,
            )

    def _chg_require_change(self, change_id: str) -> Change:
        change = self.db.change.get(change_id)
        if change is None:
            raise ItsmError(
                f"Change not found with identifier '{change_id}'",
                code="NOT_FOUND", field="change_id",
            )
        return change

    def _next_change_number(self) -> str:
        """Human change number ``CHG{seq:07d}`` over the numeric tail of existing numbers."""
        seqs = []
        for change in self.db.change.values():
            tail = "".join(ch for ch in change.number if ch.isdigit())
            if tail:
                seqs.append(int(tail))
        seq = (max(seqs) + 1) if seqs else 1
        return f"CHG{seq:07d}"

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def create_change(
        self,
        short_description: str,
        status: str,
        impact: str,
        risk: str,
        priority: str,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        implementation_plan: Optional[str] = None,
        testing_plan: Optional[str] = None,
        cab_required: Optional[bool] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        close_code: Optional[str] = None,
        close_notes: Optional[str] = None,
    ) -> Change:
        """Create a new change request.

        The requester and org are taken from the acting (authenticated) user. The change id is
        sequential (CHG_001, CHG_002, ...) and the human number is a separate sequence
        (CHG0000001, CHG0000002, ...).

        Args:
            short_description: Brief description of the change (required, <=120 chars).
            status: Change status: new, assess, authorize, scheduled, implement, review, closed,
                canceled (required).
            impact: Impact level: high, medium, low (required).
            risk: Risk level: high, medium, low (required).
            priority: Priority level: critical, high, moderate, low (required).
            service: Affected business service id.
            service_offering: Affected service offering id.
            configuration_item: Affected configuration item id.
            category: Change category (network, software, hardware, documentation,
                system_software, application_software, service, telecom, other); defaults to
                'other'.
            description: Detailed description (<=120 chars).
            implementation_plan: Implementation plan (<=120 chars).
            testing_plan: Testing plan (<=120 chars).
            cab_required: Whether CAB approval is required; defaults to False.
            assigned_to: Assigned user id.
            assignment_group: Assigned group id.
            close_code: Close code (successful, successful_with_issues, unsuccessful).
            close_notes: Close notes (<=120 chars).

        Returns:
            The created change request.
        """
        self._require_user(assigned_to, "assigned_to")
        self._require_group(assignment_group)
        self._require_ci(configuration_item)
        self._chg_require_service(service)
        self._chg_require_service_offering(service_offering)

        requested_by = self.acting_user_id or self._first_admin_id()
        change_id, _ = self._make_id(self.db.change, "CHG")
        now = self._now()
        change = Change(
            change_id=change_id,
            number=self._next_change_number(),
            short_description=short_description,
            requested_by=requested_by,
            service=service,
            service_offering=service_offering,
            configuration_item=configuration_item,
            assigned_to=assigned_to,
            assignment_group=assignment_group,
            org_id=self._org_of_user(requested_by),
            status=status,
            category=category or "other",
            description=description,
            implementation_plan=implementation_plan,
            testing_plan=testing_plan,
            close_notes=close_notes,
            cab_required=cab_required if cab_required is not None else False,
            impact=impact,
            priority=priority,
            risk=risk,
            close_code=close_code,
            created_on=now,
            updated_on=now,
        )
        self.db.change[change_id] = change
        return change

    @is_tool(ToolType.WRITE)
    def update_change(
        self,
        change_id: str,
        number: Optional[str] = None,
        requested_by: Optional[str] = None,
        short_description: Optional[str] = None,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        implementation_plan: Optional[str] = None,
        testing_plan: Optional[str] = None,
        cab_required: Optional[bool] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        close_code: Optional[str] = None,
        close_notes: Optional[str] = None,
        status: Optional[str] = None,
        impact: Optional[str] = None,
        risk: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> Change:
        """Update an existing change request. Only the fields you pass are changed.

        Raises if no updatable fields are provided, or if every provided field already equals the
        stored value (no-op update).

        Args:
            change_id: Id of the change to update (required).
            number: Change number (CHG0000001, ...).
            requested_by: User id who requested the change.
            short_description: Brief description (<=120 chars).
            service: Affected business service id.
            service_offering: Affected service offering id.
            configuration_item: Affected configuration item id.
            category: Change category (network, software, hardware, documentation,
                system_software, application_software, service, telecom, other).
            description: Detailed description (<=120 chars).
            implementation_plan: Implementation plan (<=120 chars).
            testing_plan: Testing plan (<=120 chars).
            cab_required: Whether CAB approval is required.
            assigned_to: Assigned user id.
            assignment_group: Assigned group id.
            close_code: Close code (successful, successful_with_issues, unsuccessful).
            close_notes: Close notes (<=120 chars).
            status: Change status (new, assess, authorize, scheduled, implement, review, closed,
                canceled).
            impact: Impact level (high, medium, low).
            risk: Risk level (high, medium, low).
            priority: Priority level (critical, high, moderate, low).

        Returns:
            The updated change request.
        """
        updates = {
            "number": number, "requested_by": requested_by,
            "short_description": short_description, "service": service,
            "service_offering": service_offering, "configuration_item": configuration_item,
            "category": category, "description": description,
            "implementation_plan": implementation_plan, "testing_plan": testing_plan,
            "cab_required": cab_required, "assigned_to": assigned_to,
            "assignment_group": assignment_group, "close_code": close_code,
            "close_notes": close_notes, "status": status, "impact": impact,
            "risk": risk, "priority": priority,
        }
        provided = {k: v for k, v in updates.items() if v is not None}
        if not provided:
            raise ItsmError("No fields provided for update", code="VALIDATION_ERROR")

        change = self._chg_require_change(change_id)
        self._require_user(requested_by, "requested_by")
        self._require_user(assigned_to, "assigned_to")
        self._require_group(assignment_group)
        self._require_ci(configuration_item)
        self._chg_require_service(service)
        self._chg_require_service_offering(service_offering)

        unchanged = [k for k, v in provided.items() if getattr(change, k) == v]
        if len(unchanged) == len(provided):
            joined = ", ".join(
                f"{k} (already {getattr(change, k)!r})" for k in unchanged
            )
            raise ItsmError(
                f"No changes detected for fields: {joined}",
                code="NO_CHANGES_DETECTED",
            )

        for field, value in provided.items():
            setattr(change, field, value)
        change.updated_on = self._now()
        return change

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_change_by_number(self, number: str) -> Change:
        """Return the change with the given human-readable number.

        Args:
            number: The change number, e.g. 'CHG0000001'.

        Returns:
            The first matching change.
        """
        for change in self.db.change.values():
            if change.number == number:
                return change
        raise ItsmError(
            f"Change not found with identifier '{number}'",
            code="NOT_FOUND", field="number",
        )

    @is_tool(ToolType.READ)
    def list_changes(
        self,
        change_id: Optional[str] = None,
        number: Optional[str] = None,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        requested_by: Optional[str] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        impact: Optional[str] = None,
        risk: Optional[str] = None,
        priority: Optional[str] = None,
        close_code: Optional[str] = None,
        short_description: Optional[str] = None,
        description: Optional[str] = None,
        implementation_plan: Optional[str] = None,
        testing_plan: Optional[str] = None,
        close_notes: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> List[Change]:
        """List changes, optionally filtered. All filters are ANDed; omitted filters ignored.

        Id/enum filters match exactly; text filters (short_description, description,
        implementation_plan, testing_plan, close_notes) match case-insensitively as substrings.

        Args:
            change_id: Filter by change id (exact).
            number: Filter by change number (exact).
            service: Filter by service id (exact).
            service_offering: Filter by service offering id (exact).
            configuration_item: Filter by configuration item id (exact).
            requested_by: Filter by requester user id (exact).
            assigned_to: Filter by assignee user id (exact).
            assignment_group: Filter by assignment group id (exact).
            status: Filter by status (exact).
            category: Filter by category (exact).
            impact: Filter by impact (exact).
            risk: Filter by risk (exact).
            priority: Filter by priority (exact).
            close_code: Filter by close code (exact).
            short_description: Filter by short description (partial, case-insensitive).
            description: Filter by description (partial, case-insensitive).
            implementation_plan: Filter by implementation plan (partial, case-insensitive).
            testing_plan: Filter by testing plan (partial, case-insensitive).
            close_notes: Filter by close notes (partial, case-insensitive).
            created_after: Only changes created strictly after this ISO timestamp.
            created_before: Only changes created on/before this ISO timestamp.

        Returns:
            The list of matching changes.
        """
        eq_filters = {
            "change_id": change_id, "number": number, "service": service,
            "service_offering": service_offering, "configuration_item": configuration_item,
            "requested_by": requested_by, "assigned_to": assigned_to,
            "assignment_group": assignment_group, "status": status, "category": category,
            "impact": impact, "risk": risk, "priority": priority, "close_code": close_code,
        }
        partial_filters = {
            "short_description": short_description, "description": description,
            "implementation_plan": implementation_plan, "testing_plan": testing_plan,
            "close_notes": close_notes,
        }
        active_eq = {k: v for k, v in eq_filters.items() if v is not None}
        active_partial = {k: v for k, v in partial_filters.items() if v is not None}

        out: List[Change] = []
        for change in self.db.change.values():
            if any(getattr(change, attr) != val for attr, val in active_eq.items()):
                continue
            skip = False
            for attr, val in active_partial.items():
                current = getattr(change, attr)
                if current is None or val.lower() not in current.lower():
                    skip = True
                    break
            if skip:
                continue
            if created_after is not None and (change.created_on or "") <= created_after:
                continue
            if created_before is not None and (change.created_on or "") > created_before:
                continue
            out.append(change)
        return out

    @is_tool(ToolType.READ)
    def get_changes_assigned_to(
        self, assignment_group: Optional[str] = None, assigned_to: Optional[str] = None
    ) -> List[Change]:
        """List changes assigned to a user and/or assignment group.

        At least one of assignment_group or assigned_to must be provided.

        Args:
            assignment_group: Assignment group id to filter by.
            assigned_to: Assignee user id to filter by.

        Returns:
            The list of matching changes.
        """
        if assignment_group is None and assigned_to is None:
            raise ItsmError(
                "At least one of assignment_group or assigned_to must be provided",
                code="VALIDATION_ERROR",
            )
        out: List[Change] = []
        for change in self.db.change.values():
            if assignment_group is not None and change.assignment_group != assignment_group:
                continue
            if assigned_to is not None and change.assigned_to != assigned_to:
                continue
            out.append(change)
        return out

    # ------------------------------------------------------------------ private
    def _first_admin_id(self) -> str:
        for uid, user in self.db.users.items():
            if user.role == "admin":
                return uid
        first = next(iter(self.db.users), None)
        if first is None:
            raise ItsmError("No users available to attribute the change to")
        return first
