"""Incident-knowledge link tools (3) — faithful port of the ITSM MCP's
``incident_knowledges`` category.

Covers searching incident<->knowledge links, linking a knowledge article to an incident, and
removing such links.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import IncidentKnowledge
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool

_VALID_USED_AS = ("suggested", "applied", "resolution")


class IncidentKnowledgeToolsMixin(ItsmToolsBase):
    """Incident-knowledge link management tools."""

    # ----------------------------------------------------------------- helpers
    def _require_knowledge(self, knowledge_id: str, field: str = "knowledge_id"):
        kb = self.db.knowledge.get(knowledge_id)
        if kb is None:
            raise ItsmError(
                f"Knowledge article '{knowledge_id}' not found",
                code="RESOURCE_NOT_FOUND", field=field,
            )
        return kb

    @staticmethod
    def _parse_used_as(used_as: str) -> List[str]:
        """Split a single/comma-separated ``used_as`` filter into validated lowercase values."""
        values = [v.strip() for v in used_as.split(",") if v.strip()]
        invalid = [v for v in values if v not in _VALID_USED_AS]
        if invalid:
            raise ItsmError(
                f"Invalid value(s) for 'used_as': {', '.join(invalid)}. Must be one or more of: "
                f"suggested, applied, resolution (comma-separated, lowercase only)",
                code="INVALID_ENUM_VALUE", field="used_as",
            )
        return values

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_incident_knowledge_links(
        self,
        incident_kb_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        knowledge_id: Optional[str] = None,
        used_as: Optional[str] = None,
    ) -> List[IncidentKnowledge]:
        """Find incident-knowledge links with optional filters.

        All provided filters are ANDed; omitted filters are ignored.

        Args:
            incident_kb_id: Filter by incident knowledge link id.
            incident_id: Filter by incident id.
            knowledge_id: Filter by knowledge article id.
            used_as: Filter by usage type(s). A single value or comma-separated list of values
                (e.g. 'suggested,applied,resolution' or 'suggested, applied, resolution'); valid
                values (lowercase only) are suggested, applied, resolution. Returns links matching
                any of the specified values.

        Returns:
            The list of matching incident-knowledge links.
        """
        used_as_values = self._parse_used_as(used_as) if used_as is not None else None
        out: List[IncidentKnowledge] = []
        for link in self.db.incident_knowledge.values():
            if incident_kb_id is not None and link.incident_kb_id != incident_kb_id:
                continue
            if incident_id is not None and link.incident_id != incident_id:
                continue
            if knowledge_id is not None and link.knowledge_id != knowledge_id:
                continue
            if used_as_values is not None and link.used_as not in used_as_values:
                continue
            out.append(link)
        return out

    # ----------------------------------------------------------------- writes
    @is_tool(ToolType.WRITE)
    def link_knowledge_to_incident(
        self,
        incident_id: str,
        knowledge_id: str,
        used_as: Optional[str] = None,
    ) -> IncidentKnowledge:
        """Link a knowledge article to an incident. Creates a new incident-knowledge link.

        Args:
            incident_id: Incident id to link knowledge to (required).
            knowledge_id: Knowledge article id to link (required).
            used_as: How the knowledge was used (suggested, applied, resolution);
                defaults to 'suggested'.

        Returns:
            The created incident-knowledge link.
        """
        incident = self._require_incident(incident_id)
        self._require_knowledge(knowledge_id)

        org_id = incident.org_id
        for link in self.db.incident_knowledge.values():
            if (link.org_id == org_id and link.incident_id == incident_id
                    and link.knowledge_id == knowledge_id):
                raise ItsmError(
                    "UNIQUE constraint failed: incident_knowledge.org_id, "
                    "incident_knowledge.incident_id, incident_knowledge.knowledge_id",
                    code="CONSTRAINT_VIOLATION",
                )

        incident_kb_id, _ = self._make_id(self.db.incident_knowledge, "IKB")
        now = self._now()
        link = IncidentKnowledge(
            incident_kb_id=incident_kb_id,
            incident_id=incident_id,
            knowledge_id=knowledge_id,
            org_id=org_id,
            used_as=used_as or "suggested",
            created_on=now,
            updated_on=now,
        )
        self.db.incident_knowledge[incident_kb_id] = link
        return link

    @is_tool(ToolType.WRITE)
    def remove_knowledge_link_to_incident(
        self,
        incident_kb_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        knowledge_id: Optional[str] = None,
        used_as: Optional[str] = None,
    ) -> dict:
        """Remove a knowledge link from an incident.

        Identify the link either by ``incident_kb_id`` OR by the combination of ``incident_id``
        and ``knowledge_id``. When selecting by ``incident_kb_id`` the ``used_as`` filter is
        ignored; when selecting by the incident/knowledge pair, ``used_as`` further constrains
        the match.

        Args:
            incident_kb_id: Incident knowledge link id to remove.
            incident_id: Incident id (must be used with knowledge_id).
            knowledge_id: Knowledge article id (must be used with incident_id).
            used_as: Usage type to filter removal (suggested, applied, resolution).

        Returns:
            A confirmation message dict.
        """
        if incident_kb_id is not None:
            link = self.db.incident_knowledge.get(incident_kb_id)
            if link is None:
                raise ItsmError(
                    f"Incident knowledge link '{incident_kb_id}' not found",
                    code="LINK_NOT_FOUND",
                )
            del self.db.incident_knowledge[incident_kb_id]
            return {"message": "Knowledge link removed successfully"}

        if incident_id is None or knowledge_id is None:
            raise ItsmError(
                "Either incident_kb_id or both incident_id and knowledge_id must be provided",
                code="MISSING_IDENTIFIERS",
            )

        target_id: Optional[str] = None
        for link_id, link in self.db.incident_knowledge.items():
            if link.incident_id != incident_id or link.knowledge_id != knowledge_id:
                continue
            if used_as is not None and link.used_as != used_as:
                continue
            target_id = link_id
            break

        if target_id is None:
            raise ItsmError(
                f"Incident knowledge link '{incident_id}-{knowledge_id}' not found",
                code="LINK_NOT_FOUND",
            )
        del self.db.incident_knowledge[target_id]
        return {"message": "Knowledge link removed successfully"}
