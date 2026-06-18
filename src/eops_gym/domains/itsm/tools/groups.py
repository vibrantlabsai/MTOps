"""Group tools (7) — faithful port of the ITSM MCP's groups category.

Covers user-group CRUD/search and group-membership management.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm import enums
from eops_gym.domains.itsm.data_model import UserGroup, UserGroupMember
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool


class GroupToolsMixin(ItsmToolsBase):
    """User-group and group-membership management tools."""

    # ----------------------------------------------------------------- helpers
    def _validate_group_enums(self, *, type=None) -> None:
        """Reject out-of-set enum values, mirroring the reference's request-body enum gate."""
        self._check_enum("type", type, enums.GROUP_TYPE)

    def _require_group_exists(self, group_id: str) -> UserGroup:
        group = self.db.user_group.get(group_id)
        if group is None:
            raise ItsmError(
                f"User group not found with identifier '{group_id}'",
                code="NOT_FOUND", field="group_id",
            )
        return group

    def _require_user_exists(self, user_id: str, field: str = "user_id"):
        user = self.db.users.get(user_id)
        if user is None:
            raise ItsmError(
                f"User not found with identifier '{user_id}'",
                code="NOT_FOUND", field=field,
            )
        return user

    def _name_in_use(self, name: str, exclude_group_id: Optional[str] = None) -> bool:
        for gid, g in self.db.user_group.items():
            if gid == exclude_group_id:
                continue
            if g.name == name:
                return True
        return False

    @staticmethod
    def _normalize_ts(value: Optional[str]) -> str:
        """SQLite stores ``created_on`` with a space separator; our records use 'T'.

        Date filters in the original MCP are a lexicographic comparison against the space-form
        stored value, so normalize 'T' -> ' ' before comparing to the raw filter value.
        """
        return (value or "").replace("T", " ", 1)

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def add_new_user_group(
        self,
        name: str,
        type: str,
        manager_id: str,
        active: Optional[bool] = None,
        email: Optional[str] = None,
        description: Optional[str] = None,
    ) -> UserGroup:
        """Add a new user group. The group name must be unique across all groups.

        Args:
            name: The group's name (must be unique). Required.
            type: The group's type (e.g. 'IT Support', 'Service Desk'). Required.
            manager_id: User id of the group manager; the user must have the manager role. Required.
            active: Whether the group is active; defaults to True.
            email: The group's email address.
            description: The group's description.

        Returns:
            The newly created user group.
        """
        # Enum validation first (the reference validates the request body before manager FK checks).
        self._validate_group_enums(type=type)
        manager = self._require_user_exists(manager_id, field="manager_id")
        if manager.role != "manager":
            raise ItsmError(
                f"User '{manager_id}' does not have manager role (current role: {manager.role})",
                code="INVALID_MANAGER_ROLE", field="manager_id",
            )
        if self._name_in_use(name):
            raise ItsmError(
                f"A group with name '{name}' already exists",
                code="DUPLICATE_GROUP_NAME", field="name",
            )
        if email is not None and any(g.email == email for g in self.db.user_group.values()):
            raise ItsmError(
                f"A group with email '{email}' already exists",
                code="DUPLICATE_GROUP_EMAIL", field="email",
            )

        group_id, _ = self._make_id(self.db.user_group, "GROUP")
        now = self._now()
        group = UserGroup(
            group_id=group_id,
            name=name,
            type=type,
            active=True if active is None else active,
            email=email,
            description=description,
            manager_id=manager_id,
            org_id=self._acting_org(),
            created_on=now,
            updated_on=now,
        )
        self.db.user_group[group_id] = group
        return group

    @is_tool(ToolType.WRITE)
    def update_user_group(
        self,
        group_id: str,
        name: Optional[str] = None,
        type: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> UserGroup:
        """Update a user group. At least one of name/type/active must be provided.

        Args:
            group_id: Id of the group to update. Required.
            name: Updated group name (must remain unique).
            type: Updated group type.
            active: Updated active status.

        Returns:
            The updated user group.
        """
        self._validate_group_enums(type=type)
        group = self._require_group_exists(group_id)

        provided = {
            "name": name,
            "type": type,
            "active": active,
        }
        provided = {k: v for k, v in provided.items() if v is not None}
        if not provided:
            raise ItsmError(
                "At least one field must be provided for update",
                code="VALIDATION_ERROR",
            )

        if "name" in provided and self._name_in_use(provided["name"], exclude_group_id=group_id):
            raise ItsmError(
                f"A group with name '{provided['name']}' already exists",
                code="DUPLICATE_GROUP_NAME", field="name",
            )

        unchanged = {k: v for k, v in provided.items() if getattr(group, k) == v}
        if len(unchanged) == len(provided):
            same = ", ".join(f"{k}={v!r}" for k, v in provided.items())
            raise ItsmError(
                "No changes detected. All provided fields already have the same values: "
                f"{same}. Please provide different values or omit unchanged fields.",
                code="NO_CHANGES_DETECTED",
            )

        for field, value in provided.items():
            setattr(group, field, value)
        return group

    @is_tool(ToolType.WRITE)
    def add_new_group_member(self, group_id: str, user_id: str) -> UserGroupMember:
        """Add a user to a group. Fails if the user is already a member of the group.

        Args:
            group_id: Id of the group to add the member to. Required.
            user_id: Id of the user to add. Required.

        Returns:
            The newly created group membership.
        """
        group = self._require_group_exists(group_id)
        self._require_user_exists(user_id)

        for m in self.db.user_group_member.values():
            if m.group_id == group_id and m.user_id == user_id:
                raise ItsmError(
                    f"User '{user_id}' is already a member of group '{group_id}'",
                    code="DUPLICATE_MEMBERSHIP",
                )

        member_id, _ = self._make_id(self.db.user_group_member, "MEMBER")
        now = self._now()
        member = UserGroupMember(
            member_id=member_id,
            group_id=group_id,
            user_id=user_id,
            org_id=group.org_id,
            created_on=now,
            updated_on=now,
        )
        self.db.user_group_member[member_id] = member
        return member

    @is_tool(ToolType.WRITE)
    def remove_group_membership(
        self,
        group_id: str,
        user_id: str,
        member_id: Optional[str] = None,
    ) -> dict:
        """Remove a user's membership from a group.

        Args:
            group_id: Id of the group. Required.
            user_id: Id of the user whose membership to remove. Required.
            member_id: Optional membership id; if given it must name the membership row for this
                exact group and user.

        Returns:
            A success message.
        """
        self._require_group_exists(group_id)
        self._require_user_exists(user_id)

        if member_id:
            target = self.db.user_group_member.get(member_id)
            if target is None or target.group_id != group_id or target.user_id != user_id:
                raise ItsmError(
                    f"Group member not found with identifier '{member_id}'",
                    code="NOT_FOUND", field="member_id",
                )
            del self.db.user_group_member[member_id]
            return {"message": "Group membership removed successfully"}

        for mid, m in self.db.user_group_member.items():
            if m.group_id == group_id and m.user_id == user_id:
                del self.db.user_group_member[mid]
                return {"message": "Group membership removed successfully"}

        raise ItsmError(
            f"Group membership not found with identifier 'group_id={group_id}, user_id={user_id}'",
            code="NOT_FOUND",
        )

    # ------------------------------------------------------------------- reads
    @is_tool(ToolType.READ)
    def find_group_by_name(self, name: str) -> UserGroup:
        """Find a user group by its exact (case-sensitive) name.

        Args:
            name: The exact name of the user group to find.

        Returns:
            The matching user group.
        """
        for g in self.db.user_group.values():
            if g.name == name:
                return g
        raise ItsmError(
            f"User group not found with identifier '{name}'",
            code="NOT_FOUND", field="name",
        )

    @is_tool(ToolType.READ)
    def list_user_groups(
        self,
        group_id: Optional[str] = None,
        name: Optional[str] = None,
        active: Optional[bool] = None,
        type: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> dict:
        """List user groups, optionally filtered. Results are ordered by created_on descending.

        Args:
            group_id: Filter by group id (exact match).
            name: Filter by group name (partial, case-sensitive substring match).
            active: Filter by active status.
            type: Filter by group type.
            created_after: Only groups created strictly after this date (ISO 8601).
            created_before: Only groups created strictly before this date (ISO 8601).

        Returns:
            A mapping with 'user_groups' (the matching groups) and 'total_count'.
        """
        # The reference validates enum-typed filters too (invalid value -> error, not empty result).
        self._validate_group_enums(type=type)
        out: List[UserGroup] = []
        for g in self.db.user_group.values():
            if group_id is not None and g.group_id != group_id:
                continue
            if name is not None and name not in g.name:
                continue
            if active is not None and g.active != active:
                continue
            if type is not None and g.type != type:
                continue
            ts = self._normalize_ts(g.created_on)
            if created_after is not None and not ts > created_after:
                continue
            if created_before is not None and not ts < created_before:
                continue
            out.append(g)
        out.sort(key=lambda g: (g.created_on or ""), reverse=True)
        return {"user_groups": [g.model_dump() for g in out], "total_count": len(out)}

    @is_tool(ToolType.READ)
    def list_group_members(
        self,
        member_id: Optional[str] = None,
        group_id: Optional[str] = None,
        user_id: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> dict:
        """List group members, optionally filtered. Results are ordered by created_on descending.

        Args:
            member_id: Filter by membership id (exact match).
            group_id: Filter by group id (exact match).
            user_id: Filter by user id (exact match).
            created_after: Only memberships created strictly after this date (ISO 8601).
            created_before: Only memberships created strictly before this date (ISO 8601).

        Returns:
            A mapping with 'group_members' (the matching memberships) and 'total_count'.
        """
        out: List[UserGroupMember] = []
        for m in self.db.user_group_member.values():
            if member_id is not None and m.member_id != member_id:
                continue
            if group_id is not None and m.group_id != group_id:
                continue
            if user_id is not None and m.user_id != user_id:
                continue
            ts = self._normalize_ts(m.created_on)
            if created_after is not None and not ts > created_after:
                continue
            if created_before is not None and not ts < created_before:
                continue
            out.append(m)
        out.sort(key=lambda m: (m.created_on or ""), reverse=True)
        return {"group_members": [m.model_dump() for m in out], "total_count": len(out)}
