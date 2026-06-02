"""Knowledge tools (3) — faithful port of the ITSM MCP's knowledge category.

Covers knowledge-article create/retrieve/update. Verified against the live MCP by the
differential conformance test.

Notes from probing the oracle:
- ``knowledge_id`` is ``KB_<maxseq+1:03d>`` over ALL existing rows (global, not per-org).
- ``kb_number`` is ``KB<maxnum+1:07d>`` where ``maxnum`` is the largest numeric kb_number across
  ALL rows (global — the seed legitimately repeats kb_numbers across orgs, but generation keys
  off the global max).
- ``org_id`` is the acting/caller user's org (NOT the owner's org).
- ``short_description`` is never set by tools; it stays NULL on create (no such param).
- create defaults: ``state='published'``, ``visibility='internal'``.
- ``owner_id`` is FK-validated (error code USER_NOT_FOUND, field ``owner_id``).
- update routes on ``knowledge_id`` only; ``kb_number`` is accepted in the schema but the server
  requires ``knowledge_id`` (passing only ``kb_number`` yields a missing-path-param error).
- retrieve returns ``{"knowledges": [...], "total_count": N}`` across ALL orgs, sorted by
  ``created_on`` descending; ``created_after`` is strict (>) and ``created_before`` is inclusive
  (<=); ``title``/``body`` are case-insensitive partial matches.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import Knowledge
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool


class KnowledgeToolsMixin(ItsmToolsBase):
    """Knowledge-base article management tools."""

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _kb_number_seq(collection: dict) -> int:
        """Next sequential integer for ``KB<NNNNNNN>`` numbers (max numeric + 1; 1 if empty)."""
        seqs = []
        for rec in collection.values():
            num = getattr(rec, "kb_number", None)
            if num and num.startswith("KB") and num[2:].isdigit():
                seqs.append(int(num[2:]))
        return (max(seqs) + 1) if seqs else 1

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def create_knowledge_article(
        self,
        title: str,
        owner_id: str,
        body: Optional[str] = None,
        state: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> Knowledge:
        """Create a new knowledge article.

        The system auto-generates ``knowledge_id`` (KB_001, KB_002, ...) and ``kb_number``
        (KB0000001, KB0000002, ...) and timestamps. The article is scoped to the acting user's
        organization.

        Args:
            title: Article title (required, 1-120 characters).
            owner_id: User id who owns the article (author/responsible person, required).
            body: Full article content (detailed explanation, solutions, troubleshooting steps).
            state: Article state (draft, review, published, retired); defaults to 'published'.
            visibility: Article visibility (internal, external); defaults to 'internal'.

        Returns:
            The created knowledge article.
        """
        self._require_user(owner_id, "owner_id")

        knowledge_id, _ = self._make_id(self.db.knowledge, "KB")
        kb_seq = self._kb_number_seq(self.db.knowledge)
        now = self._now()
        article = Knowledge(
            knowledge_id=knowledge_id,
            kb_number=f"KB{kb_seq:07d}",
            title=title,
            short_description=None,  # tools never set short_description (only the seed bakes it)
            body=body,
            state=state or "published",
            visibility=visibility or "internal",
            owner_id=owner_id,
            org_id=self._acting_org(),
            created_on=now,
            updated_on=now,
        )
        self.db.knowledge[knowledge_id] = article
        return article

    @is_tool(ToolType.WRITE)
    def update_knowledge_article(
        self,
        knowledge_id: Optional[str] = None,
        kb_number: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[str] = None,
        visibility: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Knowledge:
        """Update a knowledge article by its ``knowledge_id``. Only passed fields are changed.

        The article is located by ``knowledge_id``. ``kb_number`` is accepted for compatibility
        but the underlying server requires ``knowledge_id`` to identify the record.

        Args:
            knowledge_id: Unique identifier of the article to update (e.g., KB_001).
            kb_number: KB number of the article (e.g., KB0000001), mutually exclusive with knowledge_id; the server routes on knowledge_id, so knowledge_id must be provided.
            title: Updated title (1-120 characters).
            body: Updated body content.
            state: Updated state (draft, review, published, retired).
            visibility: Updated visibility (internal, external).
            owner_id: Updated owner user id.

        Returns:
            The updated knowledge article.
        """
        if knowledge_id is None:
            # The server requires knowledge_id as a path parameter (kb_number alone is rejected).
            raise ItsmError("Field required", code="VALIDATION_ERROR", field="knowledge_id")

        article = self.db.knowledge.get(knowledge_id)
        if article is None:
            raise ItsmError(
                f"Knowledge article not found with identifier '{knowledge_id}'",
                code="NOT_FOUND",
                field=None,
            )

        self._require_user(owner_id, "owner_id")

        updates = {
            "title": title, "body": body, "state": state,
            "visibility": visibility, "owner_id": owner_id,
        }
        for field, value in updates.items():
            if value is not None:
                setattr(article, field, value)
        article.updated_on = self._now()
        return article

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def retrieve_knowledge_articles(
        self,
        knowledge_id: Optional[str] = None,
        kb_number: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[str] = None,
        visibility: Optional[str] = None,
        owner_id: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> dict:
        """List knowledge articles with optional filters (all ANDed). No filters returns all.

        Articles are returned across all organizations, sorted by creation time (newest first).

        Args:
            knowledge_id: Filter by knowledge id (exact match, e.g., KB_001).
            kb_number: Filter by KB number (exact match, e.g., KB0000001).
            title: Filter by title (partial match, case-insensitive).
            body: Filter by body content (partial match, case-insensitive).
            state: Filter by article state (draft, review, published, retired).
            visibility: Filter by visibility level (internal, external).
            owner_id: Filter by owner user id (exact match).
            created_after: Only articles created strictly after this ISO 8601 timestamp.
            created_before: Only articles created on or before this ISO 8601 timestamp.

        Returns:
            A mapping with 'knowledges' (the matching articles) and 'total_count'.
        """
        out: List[Knowledge] = []
        for art in self.db.knowledge.values():
            if knowledge_id is not None and art.knowledge_id != knowledge_id:
                continue
            if kb_number is not None and art.kb_number != kb_number:
                continue
            if title is not None and title.lower() not in (art.title or "").lower():
                continue
            if body is not None and body.lower() not in (art.body or "").lower():
                continue
            if state is not None and art.state != state:
                continue
            if visibility is not None and art.visibility != visibility:
                continue
            if owner_id is not None and art.owner_id != owner_id:
                continue
            if created_after is not None and not ((art.created_on or "") > created_after):
                continue
            if created_before is not None and not ((art.created_on or "") <= created_before):
                continue
            out.append(art)

        out.sort(key=lambda a: (a.created_on or ""), reverse=True)
        return {"knowledges": out, "total_count": len(out)}
