"""Service tools (4) — faithful port of the ITSM MCP's services category.

Covers business-service CRUD and search: ``add_new_service``, ``find_service_by_name``,
``find_services``, and ``update_service``.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import Service
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool

# Canonical field order used by the MCP for duplicate/no-change detection and the
# "No changes detected" message (NOT the caller's argument order).
_UPDATE_FIELDS = (
    "name",
    "owned_by",
    "used_for",
    "status",
    "service_classification",
    "business_criticality",
    "description",
)


class ServiceToolsMixin(ItsmToolsBase):
    """Business-service management tools."""

    # -- helpers ------------------------------------------------------------
    def _svc_require_owner(self, user_id: str) -> None:
        """Validate an ``owned_by`` FK; mirror the MCP's USER_NOT_FOUND envelope."""
        if user_id not in self.db.users:
            raise ItsmError(
                f"User with ID '{user_id}' not found", code="USER_NOT_FOUND", field="owned_by"
            )

    def _name_taken(self, name: str, exclude_service_id: Optional[str] = None) -> bool:
        """True if another service already uses this exact (case-sensitive) name."""
        for svc in self.db.service.values():
            if exclude_service_id is not None and svc.service_id == exclude_service_id:
                continue
            if svc.name == name:
                return True
        return False

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def add_new_service(
        self,
        name: str,
        owned_by: str,
        used_for: Optional[str] = None,
        status: Optional[str] = None,
        service_classification: Optional[str] = None,
        business_criticality: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Service:
        """Add a new service to the system. Service name must be unique.

        Args:
            name: Service name (1-100 chars); must be unique across services (required).
            owned_by: User id of the service owner (required).
            used_for: Purpose/usage: production, QA, test, development; defaults to 'production'.
            status: Service status: operational, non-operational, repair_in_progress, ready,
                retired; defaults to 'operational'.
            service_classification: Classification: business, technology-management,
                application; defaults to 'business'.
            business_criticality: Criticality: critical, somewhat-critical, less-critical,
                not-critical; defaults to 'critical'.
            description: Free-text description of the service.

        Returns:
            The newly created service.
        """
        if self._name_taken(name):
            raise ItsmError(
                f"A service with name '{name}' already exists",
                code="DUPLICATE_SERVICE_NAME",
                field="name",
            )
        self._svc_require_owner(owned_by)

        service_id, _ = self._make_id(self.db.service, "SVC")
        now = self._now()
        service = Service(
            service_id=service_id,
            name=name,
            owned_by=owned_by,
            org_id=self._acting_org(),
            used_for=used_for or "production",
            status=status or "operational",
            service_classification=service_classification or "business",
            business_criticality=business_criticality or "critical",
            description=description,
            created_on=now,
            updated_on=now,
        )
        self.db.service[service_id] = service
        return service

    @is_tool(ToolType.WRITE)
    def update_service(
        self,
        service_id: str,
        name: Optional[str] = None,
        owned_by: Optional[str] = None,
        used_for: Optional[str] = None,
        status: Optional[str] = None,
        service_classification: Optional[str] = None,
        business_criticality: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Service:
        """Update service details. At least one field must be provided.

        Service name must be unique if provided. Returns an error if every provided field
        already matches the current value (idempotency validation).

        Args:
            service_id: The service's unique identifier (required).
            name: Updated service name (1-100 chars); must remain unique.
            owned_by: Updated owner user id.
            used_for: Updated usage: production, QA, test, development.
            status: Updated status: operational, non-operational, repair_in_progress, ready,
                retired.
            service_classification: Updated classification: business, technology-management,
                application.
            business_criticality: Updated criticality: critical, somewhat-critical,
                less-critical, not-critical.
            description: Updated description of the service.

        Returns:
            The updated service.
        """
        provided = {
            "name": name,
            "owned_by": owned_by,
            "used_for": used_for,
            "status": status,
            "service_classification": service_classification,
            "business_criticality": business_criticality,
            "description": description,
        }
        provided = {k: v for k, v in provided.items() if v is not None}

        if not provided:
            raise ItsmError("At least one field must be provided for update")

        service = self.db.service.get(service_id)
        if service is None:
            raise ItsmError(
                f"Service not found with identifier '{service_id}'",
                code="NOT_FOUND",
            )

        # Duplicate-name check: only when the name is changing to a value used by another service.
        if "name" in provided and provided["name"] != service.name:
            if self._name_taken(provided["name"], exclude_service_id=service_id):
                raise ItsmError(
                    f"A service with name '{provided['name']}' already exists",
                    code="DUPLICATE_SERVICE_NAME",
                    field="name",
                )

        # owned_by FK validation.
        if "owned_by" in provided:
            self._svc_require_owner(provided["owned_by"])

        # Idempotency: if every provided field already equals the current value, reject.
        if all(provided[f] == getattr(service, f) for f in provided):
            same = ", ".join(
                f"{f}={provided[f]!r}" for f in _UPDATE_FIELDS if f in provided
            )
            raise ItsmError(
                "No changes detected. All provided fields already have the same values: "
                f"{same}. Please provide different values or omit unchanged fields.",
                code="NO_CHANGES_DETECTED",
            )

        for field, value in provided.items():
            setattr(service, field, value)
        service.updated_on = self._now()
        return service

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_service_by_name(self, name: str) -> Service:
        """Find a service by its exact name.

        Args:
            name: The exact (case-sensitive) name of the service to find.

        Returns:
            The matching service.
        """
        for svc in self.db.service.values():
            if svc.name == name:
                return svc
        raise ItsmError(
            f"Service not found with identifier '{name}'", code="NOT_FOUND"
        )

    @is_tool(ToolType.READ)
    def find_services(
        self,
        service_id: Optional[str] = None,
        name: Optional[str] = None,
        owned_by: Optional[str] = None,
        used_for: Optional[str] = None,
        status: Optional[str] = None,
        service_classification: Optional[str] = None,
        business_criticality: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> dict:
        """List services with optional filters. Returns all services or filtered results.

        All filters are ANDed; omitted filters are ignored. ``name`` is a case-insensitive
        partial match; every other id/enum filter is an exact match. ``created_after`` is
        strict (>), ``created_before`` is inclusive (<=). Results are sorted by service id
        descending, matching the MCP.

        Args:
            service_id: Filter by service id (exact match).
            name: Filter by service name (case-insensitive partial match).
            owned_by: Filter by owner user id.
            used_for: Filter by usage: production, QA, test, development.
            status: Filter by status: operational, non-operational, repair_in_progress,
                ready, retired.
            service_classification: Filter by classification: business, technology-management,
                application.
            business_criticality: Filter by criticality: critical, somewhat-critical,
                less-critical, not-critical.
            created_after: Only services created strictly after this ISO 8601 timestamp.
            created_before: Only services created on/before this ISO 8601 timestamp.

        Returns:
            A dict ``{"services": [...], "total_count": N}`` of matching services.
        """
        out: List[Service] = []
        for svc in self.db.service.values():
            if service_id is not None and svc.service_id != service_id:
                continue
            if name is not None and name.lower() not in (svc.name or "").lower():
                continue
            if owned_by is not None and svc.owned_by != owned_by:
                continue
            if used_for is not None and svc.used_for != used_for:
                continue
            if status is not None and svc.status != status:
                continue
            if service_classification is not None and svc.service_classification != service_classification:
                continue
            if business_criticality is not None and svc.business_criticality != business_criticality:
                continue
            if created_after is not None and not ((svc.created_on or "") > created_after):
                continue
            if created_before is not None and not ((svc.created_on or "") <= created_before):
                continue
            out.append(svc)

        out.sort(key=lambda s: s.service_id, reverse=True)
        return {"services": out, "total_count": len(out)}
