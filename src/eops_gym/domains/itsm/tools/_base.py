"""Shared base for the ITSM toolkit: DB access, deterministic IDs, validation helpers.

Category mixins (incidents, users, …) provide the ``@is_tool`` methods and rely on the
helpers defined here. The concrete ``ItsmTools`` (in ``__init__.py``) combines all mixins with
this base so the toolkit metaclass collects every tool.

All write tools mutate the in-memory ``ItsmDB`` only. IDs and timestamps are generated
deterministically (sequential suffix + frozen clock) so gold-action replay reproduces the same
DB state for hash matching. Behaviour mirrors the live MCP (see ``docs/itsm_build_spec.md``).
"""

from __future__ import annotations

from typing import Optional

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.environment.toolkit import ToolKitBase
from eops_gym.utils.clock import get_now


class ItsmError(ValueError):
    """A domain validation error. Carries an optional code/field for richer rendering.

    Raised by tools and surfaced to the agent as a tool error (mirrors the MCP's typed errors).
    """

    def __init__(self, message: str, code: str = "VALIDATION_ERROR", field: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.field = field


class ItsmToolsBase(ToolKitBase):
    """Base toolkit holding the ITSM DB + shared helpers (no tools of its own)."""

    db: ItsmDB

    def __init__(self, db: ItsmDB, acting_user_id: Optional[str] = None) -> None:
        super().__init__(db)
        # The authenticated caller (from the task's user context). Used for org scoping;
        # defaults to the first admin in the seed when not provided.
        self.acting_user_id = acting_user_id

    # -- time ---------------------------------------------------------------
    @staticmethod
    def _now() -> str:
        return get_now()

    # -- id generation ------------------------------------------------------
    @staticmethod
    def _next_seq(collection: dict) -> int:
        """Next sequential integer for ``<PREFIX>_<NNN>`` keys (1 if empty)."""
        seqs = []
        for key in collection:
            tail = key.split("_")[-1]
            if tail.isdigit():
                seqs.append(int(tail))
        return (max(seqs) + 1) if seqs else 1

    @classmethod
    def _make_id(cls, collection: dict, prefix: str, width: int = 3) -> tuple[str, int]:
        """Return (new_id, seq) like ('INC_024', 24) for the given prefix."""
        seq = cls._next_seq(collection)
        return f"{prefix}_{seq:0{width}d}", seq

    # -- org scoping --------------------------------------------------------
    def _acting_org(self) -> str:
        """Org of the acting user; falls back to the first admin's org, else ORG_001."""
        if self.acting_user_id and self.acting_user_id in self.db.users:
            return self.db.users[self.acting_user_id].org_id
        for u in self.db.users.values():
            if u.role == "admin":
                return u.org_id
        any_user = next(iter(self.db.users.values()), None)
        return any_user.org_id if any_user else "ORG_001"

    def _org_of_user(self, user_id: str) -> str:
        user = self.db.users.get(user_id)
        if user is None:
            raise ItsmError(f"User with ID '{user_id}' not found", field="user_id")
        return user.org_id

    # -- existence checks ---------------------------------------------------
    def _require_user(self, user_id: Optional[str], field: str) -> None:
        if user_id is not None and user_id not in self.db.users:
            raise ItsmError(f"User with ID '{user_id}' not found", field=field)

    def _require_group(self, group_id: Optional[str], field: str = "assignment_group") -> None:
        if group_id is not None and group_id not in self.db.user_group:
            raise ItsmError(f"Group with ID '{group_id}' not found", field=field)

    def _require_ci(self, ci_id: Optional[str], field: str = "configuration_item") -> None:
        if ci_id is not None and ci_id not in self.db.configuration_item:
            raise ItsmError(f"Configuration item with ID '{ci_id}' not found", field=field)

    def _require_incident(self, incident_id: str, field: str = "incident_id"):
        inc = self.db.incident.get(incident_id)
        if inc is None:
            raise ItsmError(f"Incident with ID '{incident_id}' not found", field=field)
        return inc
