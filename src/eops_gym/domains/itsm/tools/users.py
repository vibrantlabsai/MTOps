"""User tools (6) — faithful port of the ITSM MCP's users category.

Covers user CRUD and the various user lookups (by id, email, name) plus filtered listing.

Behaviour confirmed empirically against the original ServiceNow MCP:
  * ``add_new_user`` generates ``user_id`` = ``USER_<seq:03d>``, ``user_name`` =
    ``<first>.<last>`` lowercased (the ``user_name`` arg is IGNORED), ``static_token`` =
    ``token_<urlsafe>`` (random — the only field that cannot reach byte parity), and inherits
    ``org_id`` from the acting user. ``location_id`` defaults to NULL.
  * Email uniqueness is scoped to the acting org; phone uniqueness is global.
  * ``update_user_details`` only touches the fields it processes (email, first_name, last_name,
    active, phone, role, location_id); ``user_name`` and ``company_id`` args are accepted but
    NEVER stored. It rejects calls with no processable field (NO_FIELDS_PROVIDED) and calls
    where every provided value already matches (NO_CHANGES_DETECTED). ``user_name`` is NOT
    regenerated when first/last names change.
  * ``list_users`` returns ``{"users": [...], "total_count": N}``. Filters: email/user_id/role
    exact; first_name/last_name case-insensitive substring; phone exact (validated format);
    active "true"/"false"; created_after strictly-greater, created_before less-or-equal.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import List, Optional

from eops_gym.domains.itsm.data_model import User
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool


class UserToolsMixin(ItsmToolsBase):
    """User management tools."""

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _gen_user_name(first_name: str, last_name: str) -> str:
        """Login name = ``<first>.<last>`` lowercased (mirrors the MCP)."""
        return f"{first_name}.{last_name}".lower()

    @staticmethod
    def _gen_static_token(user_id: str) -> str:
        """A ``token_<hash>`` auth token, DETERMINISTIC from user_id.

        The live MCP mints a random token via ``secrets``; we cannot (and need not) match that
        exact value. We derive it deterministically so gold-action replay reproduces the same
        DB state for hash matching (the token differs from the original MCP's, which is irreducible).
        """
        return f"token_{hashlib.sha256(user_id.encode()).hexdigest()}"

    def _usr_require_location(self, location_id: Optional[str]) -> None:
        if location_id is not None and location_id not in self.db.location:
            raise ItsmError(
                f"Location with ID '{location_id}' not found",
                code="LOCATION_NOT_FOUND", field="location_id",
            )

    @staticmethod
    def _usr_parse_dt(value: str) -> Optional[datetime]:
        """Parse an ISO date/datetime filter value; None if unparseable."""
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def add_new_user(
        self,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        role: str,
        active: bool,
        user_name: Optional[str] = None,
        location_id: Optional[str] = None,
    ) -> User:
        """Create a new user.

        The system auto-generates the user_id (USER_001, USER_002, ...), the user_name
        (from first.last, lowercased — any supplied user_name is ignored), and a static
        auth token. The org_id is inherited from the acting user.

        Args:
            first_name: User's first name (1-60 characters) (required).
            last_name: User's last name (1-60 characters) (required).
            email: User's email address; must be unique within the org and valid (required).
            phone: User's phone number, format '+1-415-555-0101'; must be unique (required).
            role: User's role; one of admin, manager, agent, reporter (required).
            active: Whether the user account is active (required).
            user_name: Login name (ignored; always generated from first.last).
            location_id: Location identifier.

        Returns:
            The newly created user.
        """
        self._usr_require_location(location_id)

        org_id = self._acting_org()
        for u in self.db.users.values():
            if u.email == email and u.org_id == org_id:
                raise ItsmError(
                    f"A user with email '{email}' already exists in your organization",
                    code="DUPLICATE_EMAIL", field="email",
                )
        for u in self.db.users.values():
            if u.phone == phone:
                raise ItsmError(
                    f"A user with phone '{phone}' already exists",
                    code="DUPLICATE_PHONE", field="phone",
                )

        user_id, _ = self._make_id(self.db.users, "USER")
        now = self._now()
        user = User(
            user_id=user_id,
            user_name=self._gen_user_name(first_name, last_name),
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            role=role,
            active=active,
            static_token=self._gen_static_token(user_id),
            org_id=org_id,
            location_id=location_id,
            created_on=now,
            updated_on=now,
        )
        self.db.users[user_id] = user
        return user

    @is_tool(ToolType.WRITE)
    def update_user_details(
        self,
        user_id: str,
        email: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        active: Optional[bool] = None,
        phone: Optional[str] = None,
        role: Optional[str] = None,
        user_name: Optional[str] = None,
        company_id: Optional[str] = None,
        location_id: Optional[str] = None,
    ) -> User:
        """Update specific fields of an existing user.

        At least one updatable field (email, first_name, last_name, active, phone, role or
        location_id) must be provided. Updating a field to its current value is rejected
        (no changes detected). The user_name and company_id arguments are accepted but never
        stored. user_name is not regenerated when the name changes.

        Args:
            user_id: Id of the user to update (required).
            email: Updated email address; must be unique within the org and valid.
            first_name: Updated first name (1-60 characters).
            last_name: Updated last name (1-60 characters).
            active: Updated active status.
            phone: Updated phone number, format '+1-415-555-0101'; must be unique.
            role: Updated role; one of admin, manager, agent, reporter.
            user_name: Updated login name (accepted but ignored).
            company_id: Updated company identifier (accepted but ignored).
            location_id: Updated location identifier.

        Returns:
            The updated user.
        """
        user = self.db.users.get(user_id)
        if user is None:
            raise ItsmError(
                f"User not found with identifier '{user_id}'",
                code="NOT_FOUND", field=None,
            )

        # Only these fields are processed for the update / change-detection.
        candidates = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "active": active,
            "phone": phone,
            "role": role,
            "location_id": location_id,
        }
        provided = {k: v for k, v in candidates.items() if v is not None}
        if not provided:
            raise ItsmError(
                "At least one field must be provided for update",
                code="NO_FIELDS_PROVIDED", field=None,
            )

        # Email/phone uniqueness against other users (email is org-scoped, phone global).
        if email is not None and email != user.email:
            for u in self.db.users.values():
                if u.user_id != user_id and u.email == email and u.org_id == user.org_id:
                    raise ItsmError(
                        f"Failed to update user: A user with email '{email}' already exists",
                        code="INTERNAL_ERROR", field=None,
                    )
        if phone is not None and phone != user.phone:
            for u in self.db.users.values():
                if u.user_id != user_id and u.phone == phone:
                    raise ItsmError(
                        f"Failed to update user: A user with phone '{phone}' already exists",
                        code="INTERNAL_ERROR", field=None,
                    )
        if location_id is not None and location_id != user.location_id:
            self._usr_require_location(location_id)

        # Change detection: every provided value matching current -> reject.
        changed = {k: v for k, v in provided.items() if getattr(user, k) != v}
        if not changed:
            unchanged = ", ".join(
                f"{k} (already '{getattr(user, k)}')" for k in provided
            )
            raise ItsmError(
                f"No changes detected for fields: {unchanged}",
                code="NO_CHANGES_DETECTED", field=None,
            )

        for field, value in changed.items():
            setattr(user, field, value)
        user.updated_on = self._now()
        return user

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def get_user(self, user_id: str) -> User:
        """Return the user with the given user id.

        Args:
            user_id: User's unique identifier, e.g. 'USER_003'.

        Returns:
            The matching user.
        """
        user = self.db.users.get(user_id)
        if user is None:
            raise ItsmError(
                f"User not found with identifier '{user_id}'",
                code="NOT_FOUND", field=None,
            )
        return user

    @is_tool(ToolType.READ)
    def get_user_using_email(self, email: str) -> User:
        """Return the user with the given email address.

        Args:
            email: User's email address.

        Returns:
            The matching user.
        """
        for user in self.db.users.values():
            if user.email == email:
                return user
        raise ItsmError(
            f"User not found with identifier '{email}'",
            code="NOT_FOUND", field=None,
        )

    @is_tool(ToolType.READ)
    def get_user_using_name(self, first_name: str, last_name: str) -> User:
        """Return the user matching the given first and last name (case-insensitive).

        Args:
            first_name: User's first name.
            last_name: User's last name.

        Returns:
            The matching user.
        """
        fl, ll = first_name.lower(), last_name.lower()
        for user in self.db.users.values():
            if user.first_name.lower() == fl and user.last_name.lower() == ll:
                return user
        raise ItsmError(
            f"User not found with identifier '{first_name} {last_name}'",
            code="NOT_FOUND", field=None,
        )

    @is_tool(ToolType.READ)
    def list_users(
        self,
        email: Optional[str] = None,
        user_id: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        phone: Optional[str] = None,
        role: Optional[str] = None,
        active: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> dict:
        """List users, optionally filtered. Empty-string filters are ignored.

        Args:
            email: Filter by email address (exact match).
            user_id: Filter by user id (exact match).
            first_name: Filter by first name (case-insensitive, partial match).
            last_name: Filter by last name (case-insensitive, partial match).
            phone: Filter by phone number (exact match).
            role: Filter by role (admin, manager, agent, reporter).
            active: Filter by active status ('true' or 'false').
            created_after: Only users created strictly after this ISO date/datetime.
            created_before: Only users created on/before this ISO date/datetime.

        Returns:
            A dict with the matching users and their total count.
        """
        after_dt = self._usr_parse_dt(created_after) if created_after else None
        before_dt = self._usr_parse_dt(created_before) if created_before else None
        active_bool = None
        if active:
            active_bool = active.strip().lower() == "true"

        out: List[User] = []
        for user in self.db.users.values():
            if email and user.email != email:
                continue
            if user_id and user.user_id != user_id:
                continue
            if first_name and first_name.lower() not in user.first_name.lower():
                continue
            if last_name and last_name.lower() not in user.last_name.lower():
                continue
            if phone and user.phone != phone:
                continue
            if role and user.role != role:
                continue
            if active and user.active != active_bool:
                continue
            if after_dt is not None:
                created = self._usr_parse_dt(user.created_on or "")
                if created is None or not (created > after_dt):
                    continue
            if before_dt is not None:
                created = self._usr_parse_dt(user.created_on or "")
                if created is None or not (created <= before_dt):
                    continue
            out.append(user)
        return {"users": out, "total_count": len(out)}
