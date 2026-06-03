"""SLA definition tools (4) — faithful port of the ITSM MCP's sla_definitions category.

Covers SLA-definition create, lookup-by-name, filtered list, and update. Verified against the
live MCP by the differential conformance test.

Notes (confirmed empirically against the oracle):
- ``sla_def_id`` is generated as ``SLA_<maxseq+1:03d>``.
- ``org_id`` is inherited from the acting user's org (all our tasks are ORG_001).
- Names must be globally unique (the duplicate check spans ALL orgs, not just the acting org,
  despite the DB-level ``UNIQUE(org_id, name)`` constraint), and the comparison is exact/case
  sensitive. Update excludes the record being edited from the duplicate check.
- ``schedule`` is a free-form string (not FK-validated).
- ``find_sla_definitions`` returns a dict ``{"sla_definitions": [...], "total_count": N}`` and is
  NOT org-scoped (it returns rows across every org). ``created_after`` is strict ``>``;
  ``created_before`` is inclusive ``<=``. Empty-string / null filters are ignored.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import SLADefinition
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool


class SLADefinitionToolsMixin(ItsmToolsBase):
    """SLA definition management tools."""

    # ------------------------------------------------------------------ helpers
    def _sla_require_unique_name(self, name: str, exclude_id: Optional[str] = None) -> None:
        """Raise if another SLA definition (any org) already uses this exact name."""
        for sla in self.db.sla_definition.values():
            if sla.sla_def_id == exclude_id:
                continue
            if sla.name == name:
                raise ItsmError(
                    f"SLA definition with name '{name}' already exists",
                    code="DUPLICATE_NAME",
                    field="name",
                )

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def add_new_sla_definition(
        self,
        name: str,
        metric: str,
        target_mins: int,
        pause_on_pending: bool,
        active: bool,
        applies_to_priority: Optional[str] = None,
        schedule: Optional[str] = None,
    ) -> SLADefinition:
        """Create a new SLA definition.

        Args:
            name: Unique name for the SLA definition (<=120 chars).
            metric: SLA metric, either 'response' or 'resolution'.
            target_mins: Target time in minutes (>=1).
            pause_on_pending: Whether the SLA pauses on pending status.
            active: Whether the SLA definition is active.
            applies_to_priority: Priority this SLA applies to (critical, high, moderate, low).
            schedule: Schedule id (<=32 chars).

        Returns:
            The created SLA definition.
        """
        self._sla_require_unique_name(name)

        sla_def_id, _ = self._make_id(self.db.sla_definition, "SLA")
        now = self._now()
        sla = SLADefinition(
            sla_def_id=sla_def_id,
            name=name,
            metric=metric,
            target_mins=target_mins,
            pause_on_pending=pause_on_pending,
            applies_to_priority=applies_to_priority,
            active=active,
            schedule=schedule,
            org_id=self._acting_org(),
            created_on=now,
            updated_on=now,
        )
        self.db.sla_definition[sla_def_id] = sla
        return sla

    @is_tool(ToolType.WRITE)
    def update_sla_definition(
        self,
        sla_def_id: str,
        name: Optional[str] = None,
        metric: Optional[str] = None,
        target_mins: Optional[int] = None,
        pause_on_pending: Optional[bool] = None,
        active: Optional[bool] = None,
        applies_to_priority: Optional[str] = None,
        schedule: Optional[str] = None,
    ) -> SLADefinition:
        """Update an existing SLA definition by id. Only the fields you pass are changed.

        If every provided field already equals its current value, no change is made and an error
        is raised. Renaming to a name used by a different SLA definition is rejected.

        Args:
            sla_def_id: Id of the SLA definition to update (required).
            name: New unique name for the SLA definition (<=120 chars).
            metric: SLA metric, either 'response' or 'resolution'.
            target_mins: Target time in minutes (>=1).
            pause_on_pending: Whether the SLA pauses on pending status.
            active: Whether the SLA definition is active.
            applies_to_priority: Priority this SLA applies to (critical, high, moderate, low).
            schedule: Schedule id (<=32 chars).

        Returns:
            The updated SLA definition.
        """
        sla = self.db.sla_definition.get(sla_def_id)
        if sla is None:
            raise ItsmError(
                f"SLA definition not found with identifier '{sla_def_id}'",
                code="NOT_FOUND",
                field="sla_def_id",
            )

        if name is not None and name != sla.name:
            self._sla_require_unique_name(name, exclude_id=sla_def_id)

        updates = {
            "name": name,
            "metric": metric,
            "target_mins": target_mins,
            "pause_on_pending": pause_on_pending,
            "active": active,
            "applies_to_priority": applies_to_priority,
            "schedule": schedule,
        }
        provided = {f: v for f, v in updates.items() if v is not None}
        changed = {f: v for f, v in provided.items() if getattr(sla, f) != v}
        if provided and not changed:
            unchanged = ", ".join(f"{f} (already {getattr(sla, f)})" for f in provided)
            raise ItsmError(
                f"No changes detected for fields: {unchanged}",
                code="NO_CHANGES_DETECTED",
            )

        for field, value in changed.items():
            setattr(sla, field, value)
        if changed:
            sla.updated_on = self._now()
        return sla

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_sla_definition_by_name(self, name: str) -> SLADefinition:
        """Return the SLA definition with the given unique name.

        Args:
            name: Name of the SLA definition.

        Returns:
            The matching SLA definition.
        """
        for sla in self.db.sla_definition.values():
            if sla.name == name:
                return sla
        raise ItsmError(
            f"SLA definition not found with identifier '{name}'",
            code="NOT_FOUND",
            field="name",
        )

    @is_tool(ToolType.READ)
    def find_sla_definitions(
        self,
        sla_def_id: Optional[str] = None,
        name: Optional[str] = None,
        metric: Optional[str] = None,
        target_mins: Optional[int] = None,
        pause_on_pending: Optional[bool] = None,
        applies_to_priority: Optional[str] = None,
        active: Optional[bool] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> dict:
        """List SLA definitions, applying optional filters. Returns all if no filters given.

        Empty strings and nulls are ignored (return all results without filtering). Booleans only
        filter on true/false. ``created_after`` is exclusive; ``created_before`` is inclusive.

        Args:
            sla_def_id: Filter by sla_def_id.
            name: Filter by name.
            metric: Filter by metric ('response' or 'resolution').
            target_mins: Filter by target_mins.
            pause_on_pending: Filter by pause_on_pending.
            applies_to_priority: Filter by applies_to_priority (critical, high, moderate, low).
            active: Filter by active status.
            created_after: ISO timestamp; return SLA definitions created strictly after this value.
            created_before: ISO timestamp; return SLA definitions created on/before this value.

        Returns:
            A dict with the matching ``sla_definitions`` list and their ``total_count``.
        """
        eq_filters = {
            "sla_def_id": sla_def_id,
            "name": name,
            "metric": metric,
            "target_mins": target_mins,
            "pause_on_pending": pause_on_pending,
            "applies_to_priority": applies_to_priority,
            "active": active,
        }
        active_filters = {
            k: v for k, v in eq_filters.items() if v is not None and v != ""
        }

        out: List[SLADefinition] = []
        for sla in self.db.sla_definition.values():
            if any(getattr(sla, attr) != val for attr, val in active_filters.items()):
                continue
            if created_after not in (None, "") and (sla.created_on or "") <= created_after:
                continue
            if created_before not in (None, "") and (sla.created_on or "") > created_before:
                continue
            out.append(sla)

        return {"sla_definitions": out, "total_count": len(out)}
