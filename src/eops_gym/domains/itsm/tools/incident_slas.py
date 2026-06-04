"""Incident SLA tools (5) — faithful port of the ITSM MCP's incident_slas category.

Covers incident-SLA CRUD/search plus the stage-wise breached count aggregate. The
``incident_sla`` table links an incident to an SLA definition and tracks its lifecycle stage.

Behaviour confirmed empirically against the original ServiceNow MCP:
- ``link_new_incident_sla`` generates ``TSLA_<seq>`` ids; ``stage`` defaults to ``in_progress``
  and ``has_breached`` to ``False``; ``org_id`` is always the caller's org (never derived from
  the linked incident/definition); FK existence of incident + sla_def is enforced (not org
  scoped); a duplicate ``(org_id, incident_id, sla_def_id)`` is rejected.
- ``update_incident_sla_details`` mutates only the supplied fields, never changes ``org_id``
  (even when ``incident_id`` moves cross-org), and does NOT re-check the uniqueness constraint.
- ``find_incident_slas`` / ``delete_incident_slas`` / the count aggregate operate across ALL
  orgs (no caller-org scoping, despite the catalog wording).
- ``stage`` is validated everywhere against the five valid values.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import IncidentSLA
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool

# Valid SLA stages (order mirrors the original MCP's error message + enum definition).
_VALID_STAGES = ["in_progress", "paused", "completed", "cancelled", "breached"]


class IncidentSLAToolsMixin(ItsmToolsBase):
    """Incident SLA management tools."""

    # ------------------------------------------------------------------ helpers
    def _validate_stage(self, stage: Optional[str]) -> None:
        if stage is not None and stage not in _VALID_STAGES:
            raise ItsmError(
                f"Invalid stage '{stage}'. Valid values: {_VALID_STAGES}",
                field="stage",
            )

    def _require_sla_def(self, sla_def_id: str) -> None:
        if sla_def_id not in self.db.sla_definition:
            raise ItsmError(f"SLA definition '{sla_def_id}' not found", field="sla_def_id")

    def _require_incident_sla(self, incident_sla_id: str) -> IncidentSLA:
        record = self.db.incident_sla.get(incident_sla_id)
        if record is None:
            raise ItsmError(
                f"Incident SLA '{incident_sla_id}' not found", field="incident_sla_id"
            )
        return record

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def link_new_incident_sla(
        self,
        incident_id: str,
        sla_def_id: str,
        start_time: str,
        stage: Optional[str] = None,
        has_breached: Optional[bool] = None,
        breach_time: Optional[str] = None,
        completed_time: Optional[str] = None,
    ) -> IncidentSLA:
        """Create a new incident SLA record linking an incident to an SLA definition.

        Args:
            incident_id: Incident identifier the SLA applies to (required).
            sla_def_id: SLA definition identifier (required).
            start_time: Start time of the SLA, ISO timestamp (required).
            stage: Lifecycle stage (in_progress, paused, completed, cancelled, breached);
                defaults to 'in_progress'.
            has_breached: Whether the SLA has breached; defaults to False.
            breach_time: Breach time, ISO timestamp.
            completed_time: Completion time, ISO timestamp.

        Returns:
            The created incident SLA record.
        """
        # Order mirrors the original MCP: incident FK -> sla_def FK -> uniqueness -> stage.
        self._require_incident(incident_id)
        self._require_sla_def(sla_def_id)
        org_id = self._acting_org()
        for record in self.db.incident_sla.values():
            if (
                record.org_id == org_id
                and record.incident_id == incident_id
                and record.sla_def_id == sla_def_id
            ):
                raise ItsmError(
                    f"SLA '{sla_def_id}' is already linked to incident '{incident_id}'",
                    field="sla_def_id",
                )
        self._validate_stage(stage)

        incident_sla_id, _ = self._make_id(self.db.incident_sla, "TSLA")
        now = self._now()
        record = IncidentSLA(
            incident_sla_id=incident_sla_id,
            incident_id=incident_id,
            sla_def_id=sla_def_id,
            org_id=org_id,
            stage=stage or "in_progress",
            has_breached=has_breached if has_breached is not None else False,
            start_time=start_time,
            breach_time=breach_time,
            completed_time=completed_time,
            created_on=now,
            updated_on=now,
        )
        self.db.incident_sla[incident_sla_id] = record
        return record

    @is_tool(ToolType.WRITE)
    def update_incident_sla_details(
        self,
        incident_sla_id: str,
        incident_id: Optional[str] = None,
        sla_def_id: Optional[str] = None,
        stage: Optional[str] = None,
        has_breached: Optional[bool] = None,
        start_time: Optional[str] = None,
        breach_time: Optional[str] = None,
        completed_time: Optional[str] = None,
    ) -> IncidentSLA:
        """Update an existing incident SLA record. Only the fields you pass are changed.

        Args:
            incident_sla_id: Id of the incident SLA record to update (required).
            incident_id: New incident identifier.
            sla_def_id: New SLA definition identifier.
            stage: New lifecycle stage (in_progress, paused, completed, cancelled, breached).
            has_breached: Update the breach flag.
            start_time: New start time, ISO timestamp.
            breach_time: New breach time, ISO timestamp.
            completed_time: New completion time, ISO timestamp.

        Returns:
            The updated incident SLA record.
        """
        # Order mirrors the original MCP: record existence -> incident FK -> sla_def FK -> stage.
        record = self._require_incident_sla(incident_sla_id)
        if incident_id is not None:
            self._require_incident(incident_id)
        if sla_def_id is not None:
            self._require_sla_def(sla_def_id)
        self._validate_stage(stage)

        updates = {
            "incident_id": incident_id,
            "sla_def_id": sla_def_id,
            "stage": stage,
            "has_breached": has_breached,
            "start_time": start_time,
            "breach_time": breach_time,
            "completed_time": completed_time,
        }
        for field, value in updates.items():
            if value is not None:
                setattr(record, field, value)
        record.updated_on = self._now()
        return record

    @is_tool(ToolType.WRITE)
    def delete_incident_slas(
        self,
        incident_sla_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        sla_def_id: Optional[str] = None,
        stage: Optional[str] = None,
        has_breached: Optional[bool] = None,
        created_before: Optional[str] = None,
        created_after: Optional[str] = None,
    ) -> dict:
        """Delete incident SLA records matching the given filters (all ANDed).

        At least one filter must be supplied. Deletion is not scoped to the caller's org.

        Args:
            incident_sla_id: Delete the record with this id.
            incident_id: Delete records for this incident.
            sla_def_id: Delete records for this SLA definition.
            stage: Delete records in this stage.
            has_breached: Delete records with this breach flag.
            created_before: Delete records created on or before this ISO timestamp.
            created_after: Delete records created on or after this ISO timestamp.

        Returns:
            A summary mapping with the number of records deleted.
        """
        self._validate_stage(stage)
        to_remove: List[str] = []
        for record_id, record in self.db.incident_sla.items():
            if incident_sla_id is not None and record_id != incident_sla_id:
                continue
            if incident_id is not None and record.incident_id != incident_id:
                continue
            if sla_def_id is not None and record.sla_def_id != sla_def_id:
                continue
            if stage is not None and record.stage != stage:
                continue
            if has_breached is not None and record.has_breached != has_breached:
                continue
            if created_before is not None and (record.created_on or "") > created_before:
                continue
            if created_after is not None and (record.created_on or "") < created_after:
                continue
            to_remove.append(record_id)
        for record_id in to_remove:
            del self.db.incident_sla[record_id]
        return {"deleted_count": len(to_remove)}

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_incident_slas(
        self,
        incident_sla_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        sla_def_id: Optional[str] = None,
        stage: Optional[str] = None,
        has_breached: Optional[bool] = None,
        created_before: Optional[str] = None,
        created_after: Optional[str] = None,
    ) -> dict:
        """List incident SLA records, optionally filtered. All filters are ANDed.

        Results are not scoped to the caller's org and are ordered by created_on descending.

        Args:
            incident_sla_id: Filter by SLA record id.
            incident_id: Filter by incident id.
            sla_def_id: Filter by SLA definition id.
            stage: Filter by stage (in_progress, paused, completed, cancelled, breached).
            has_breached: Filter by breach flag.
            created_before: Only records created on or before this ISO timestamp.
            created_after: Only records created on or after this ISO timestamp.

        Returns:
            A mapping with the matching records under 'incident_slas' and their 'total_count'.
        """
        self._validate_stage(stage)
        out: List[IncidentSLA] = []
        for record in self.db.incident_sla.values():
            if incident_sla_id is not None and record.incident_sla_id != incident_sla_id:
                continue
            if incident_id is not None and record.incident_id != incident_id:
                continue
            if sla_def_id is not None and record.sla_def_id != sla_def_id:
                continue
            if stage is not None and record.stage != stage:
                continue
            if has_breached is not None and record.has_breached != has_breached:
                continue
            if created_before is not None and (record.created_on or "") > created_before:
                continue
            if created_after is not None and (record.created_on or "") < created_after:
                continue
            out.append(record)
        out.sort(key=lambda r: (r.created_on or ""), reverse=True)
        return {"incident_slas": out, "total_count": len(out)}

    @is_tool(ToolType.READ)
    def find_stage_wise_breached_incident_sla_counts(
        self, stages: Optional[List[str]] = None
    ) -> dict:
        """Return counts of breached incident SLA records grouped by stage.

        Only records with has_breached=True are counted. Counts are not scoped to the caller's
        org. Stages with no breached records are omitted. The returned keys are the SLAStage
        enum names (e.g. 'SLAStage.IN_PROGRESS').

        Args:
            stages: Optional list of stages to limit the aggregation
                (in_progress, paused, completed, cancelled, breached).

        Returns:
            A mapping with per-stage breached counts under 'counts'.
        """
        if stages is not None:
            for stage in stages:
                self._validate_stage(stage)
        counts: dict = {}
        for record in self.db.incident_sla.values():
            if not record.has_breached:
                continue
            if stages is not None and record.stage not in stages:
                continue
            key = f"SLAStage.{record.stage.upper()}"
            counts[key] = counts.get(key, 0) + 1
        return {"counts": counts}
