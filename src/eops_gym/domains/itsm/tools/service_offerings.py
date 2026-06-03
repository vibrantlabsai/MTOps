"""Service offering tools (4) — faithful port of the ITSM MCP's service_offering category.

Covers service-offering search/lookup, registration, and update. Verified against the live
MCP by the differential conformance test.

Note on naming: the catalog/tool-facing API uses ``parent`` for what the schema stores as the
``business_service`` column, and ``short_description`` is a first-class column (the table's
``description`` column is never set by these tools — only the seed bakes it). ``org_id`` is the
acting (caller) user's org, not the owner's. ``used_for``/``status``/``service_classification``/
``business_criticality`` default to ``production``/``operational``/``business``/``critical``.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import ServiceOffering
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool


class ServiceOfferingToolsMixin(ItsmToolsBase):
    """Service offering management tools."""

    # ------------------------------------------------------------------ helpers
    def _so_require_service(self, service_id: Optional[str], field: str = "parent") -> None:
        """Raise if a non-None service id does not exist (FK on ``business_service``)."""
        if service_id is not None and service_id not in self.db.service:
            raise ItsmError(
                f"Service with ID '{service_id}' not found",
                code="SERVICE_NOT_FOUND", field=field,
            )

    def _so_require_owner(self, user_id: Optional[str], field: str = "owned_by") -> None:
        """Raise if a non-None user id does not exist (FK on ``owned_by``)."""
        if user_id is not None and user_id not in self.db.users:
            raise ItsmError(
                f"User with ID '{user_id}' not found",
                code="USER_NOT_FOUND", field=field,
            )

    def _so_require_unique_name(self, name: str, exclude_id: Optional[str] = None) -> None:
        """Raise if another service offering already uses ``name``."""
        for so in self.db.service_offering.values():
            if so.name == name and so.service_offering_id != exclude_id:
                raise ItsmError(
                    f"A service offering with name '{name}' already exists",
                    code="DUPLICATE_SERVICE_OFFERING_NAME", field="name",
                )

    def _require_offering(self, service_offering_id: str) -> ServiceOffering:
        """Return the offering or raise a not-found error."""
        so = self.db.service_offering.get(service_offering_id)
        if so is None:
            raise ItsmError(
                f"Service Offering not found with identifier '{service_offering_id}'",
                code="NOT_FOUND",
            )
        return so

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def register_new_service_offering(
        self,
        name: str,
        owned_by: str,
        parent: str,
        short_description: str,
        used_for: Optional[str] = None,
        status: Optional[str] = None,
        service_classification: Optional[str] = None,
        business_criticality: Optional[str] = None,
    ) -> ServiceOffering:
        """Register a new service offering. The name must be unique.

        Args:
            name: Service offering name (required, unique).
            owned_by: Owner user id (required); must reference an existing user.
            parent: Parent business service id (required); must reference an existing service.
            short_description: Short description of the service offering (required).
            used_for: Purpose/usage (production, QA, test, development); defaults to 'production'.
            status: Status (operational, non-operational, repair_in_progress, ready, retired);
                defaults to 'operational'.
            service_classification: Classification (business, technology-management, application);
                defaults to 'business'.
            business_criticality: Criticality (critical, somewhat-critical, less-critical,
                not-critical); defaults to 'critical'.

        Returns:
            The created service offering.
        """
        self._so_require_owner(owned_by)
        self._so_require_service(parent)
        self._so_require_unique_name(name)

        offering_id, _ = self._make_id(self.db.service_offering, "SVCOFF")
        now = self._now()
        offering = ServiceOffering(
            service_offering_id=offering_id,
            name=name,
            short_description=short_description,
            owned_by=owned_by,
            business_service=parent,
            org_id=self._acting_org(),
            used_for=used_for or "production",
            status=status or "operational",
            service_classification=service_classification or "business",
            business_criticality=business_criticality or "critical",
            description=None,  # MCP never derives description on create (only the seed has it)
            created_on=now,
            updated_on=now,
        )
        self.db.service_offering[offering_id] = offering
        return offering

    @is_tool(ToolType.WRITE)
    def update_service_offering(
        self,
        service_offering_id: str,
        name: Optional[str] = None,
        owned_by: Optional[str] = None,
        used_for: Optional[str] = None,
        status: Optional[str] = None,
        service_classification: Optional[str] = None,
        business_criticality: Optional[str] = None,
        short_description: Optional[str] = None,
        parent: Optional[str] = None,
    ) -> ServiceOffering:
        """Update a service offering. Only fields you pass are changed; at least one is required.

        The name must remain unique if provided. Raises if every provided field already has its
        current value (idempotency validation).

        Args:
            service_offering_id: Id of the service offering to update (required).
            name: Updated service offering name (must stay unique).
            owned_by: Updated owner user id; must reference an existing user.
            used_for: Updated usage (production, QA, test, development).
            status: Updated status (operational, non-operational, repair_in_progress, ready,
                retired).
            service_classification: Updated classification (business, technology-management,
                application).
            business_criticality: Updated criticality (critical, somewhat-critical, less-critical,
                not-critical).
            short_description: Updated short description.
            parent: Updated parent business service id; must reference an existing service.

        Returns:
            The updated service offering.
        """
        # map exposed arg name -> stored column name
        updates = {
            "name": name,
            "owned_by": owned_by,
            "used_for": used_for,
            "status": status,
            "service_classification": service_classification,
            "business_criticality": business_criticality,
            "short_description": short_description,
            "business_service": parent,
        }
        provided = {field: value for field, value in updates.items() if value is not None}
        if not provided:
            raise ItsmError("At least one field must be provided for update")

        offering = self._require_offering(service_offering_id)

        if name is not None:
            self._so_require_unique_name(name, exclude_id=service_offering_id)
        self._so_require_owner(owned_by)
        self._so_require_service(parent)

        if all(getattr(offering, field) == value for field, value in provided.items()):
            shown = ", ".join(f"{f}='{v}'" for f, v in provided.items())
            raise ItsmError(
                "No changes detected. All provided fields already have the same values: "
                f"{shown}. Please provide different values or omit unchanged fields.",
                code="NO_CHANGES_DETECTED",
            )

        for field, value in provided.items():
            setattr(offering, field, value)
        offering.updated_on = self._now()
        return offering

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_service_offering_by_name(self, name: str) -> ServiceOffering:
        """Find a service offering by its exact name.

        Args:
            name: The exact name of the service offering to find.

        Returns:
            The matching service offering.
        """
        for so in self.db.service_offering.values():
            if so.name == name:
                return so
        raise ItsmError(
            f"Service Offering not found with identifier '{name}'", code="NOT_FOUND",
        )

    @is_tool(ToolType.READ)
    def find_service_offerings(
        self,
        service_offering_id: Optional[str] = None,
        name: Optional[str] = None,
        owned_by: Optional[str] = None,
        used_for: Optional[str] = None,
        status: Optional[str] = None,
        service_classification: Optional[str] = None,
        business_criticality: Optional[str] = None,
        short_description: Optional[str] = None,
        parent: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> List[ServiceOffering]:
        """List service offerings, optionally filtered. All filters are ANDed; omitted ignored.

        ``name`` and ``short_description`` are partial, case-insensitive matches; the remaining
        filters are exact. ``parent`` matches the stored business service.

        Args:
            service_offering_id: Filter by service offering id (exact match).
            name: Filter by name (partial, case-insensitive).
            owned_by: Filter by owner user id.
            used_for: Filter by usage (production, QA, test, development).
            status: Filter by status (operational, non-operational, repair_in_progress, ready,
                retired).
            service_classification: Filter by classification (business, technology-management,
                application).
            business_criticality: Filter by criticality (critical, somewhat-critical,
                less-critical, not-critical).
            short_description: Filter by short description (partial, case-insensitive).
            parent: Filter by parent business service id.
            created_after: Only offerings created on/after this ISO 8601 timestamp.
            created_before: Only offerings created on/before this ISO 8601 timestamp.

        Returns:
            The list of matching service offerings.
        """
        # exact-match filters mapped to stored attribute names
        eq_filters = {
            "service_offering_id": service_offering_id,
            "owned_by": owned_by,
            "used_for": used_for,
            "status": status,
            "service_classification": service_classification,
            "business_criticality": business_criticality,
            "business_service": parent,
        }
        active = {k: v for k, v in eq_filters.items() if v is not None}
        out: List[ServiceOffering] = []
        for so in self.db.service_offering.values():
            if any(getattr(so, attr) != val for attr, val in active.items()):
                continue
            if name is not None and name.lower() not in (so.name or "").lower():
                continue
            if short_description is not None and (
                short_description.lower() not in (so.short_description or "").lower()
            ):
                continue
            if created_after is not None and (so.created_on or "") < created_after:
                continue
            if created_before is not None and (so.created_on or "") > created_before:
                continue
            out.append(so)
        return out
