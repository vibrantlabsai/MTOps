"""Notification tools (6) — faithful port of the ITSM MCP's notification category.

Covers notification search (by id/incident/email/type/status/date-range), the email- and
incident-scoped finders, and send/update/delete write tools.

Notable behaviours mirrored here (confirmed empirically against the original ServiceNow MCP):
  - ``send_notification`` defaults ``type`` to ``"other"`` and ``status`` to ``"queued"``;
    leaves ``subject``/``message`` NULL. It validates the incident exists, that the recipient
    email belongs to *some* user (global, not org-scoped), and refuses to send to the acting
    user's own email (``CANNOT_SEND_TO_SELF``). The new row's ``org_id`` is the acting user's org.
  - ``update_notification`` validates the notification exists (NOT_FOUND otherwise); if
    ``incident_id``/``email`` are supplied it validates incident existence / global email
    existence (no self-send check on update). It never reassigns ``org_id`` and only touches the
    fields supplied. Notifications of any org may be updated.
  - The finder tools return ``{"notifications": [...], "count": N}`` and apply NO org scoping.
    ``find_notifications_for_email`` / ``find_notifications_sent_for_incident`` raise NOT_FOUND
    (rather than returning an empty list) when nothing matches.
  - ``delete_notifications`` is registered on the live server but has no wired router endpoint,
    so it returns an "API endpoint not found" error and never mutates state. We mirror that
    exactly (raise; no DB mutation) to preserve byte-for-byte DB parity with the original MCP.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import Notification
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool


class NotificationToolsMixin(ItsmToolsBase):
    """Notification management tools."""

    # ------------------------------------------------------------------ helpers
    def _acting_email(self) -> Optional[str]:
        """Email of the acting (token) user, used for the send-to-self guard."""
        if self.acting_user_id and self.acting_user_id in self.db.users:
            return self.db.users[self.acting_user_id].email
        return None

    def _require_email_user(self, email: str) -> None:
        """Validate that ``email`` belongs to an existing user (global, any org)."""
        for user in self.db.users.values():
            if user.email == email:
                return
        raise ItsmError(
            f"User with email '{email}' not found or does not belong to your organization",
            code="USER_EMAIL_NOT_FOUND",
            field="email",
        )

    def _require_notification(self, notification_id: str) -> Notification:
        notif = self.db.notification.get(notification_id)
        if notif is None:
            raise ItsmError(
                f"Notification not found with identifier '{notification_id}'",
                code="RESOURCE_NOT_FOUND",
                field=None,
            )
        return notif

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def send_notification(
        self,
        incident_id: str,
        email: str,
        type: Optional[str] = None,
        status: Optional[str] = None,
        subject: Optional[str] = None,
        message: Optional[str] = None,
    ) -> Notification:
        """Create and send a new notification associated with an incident.

        Args:
            incident_id: Id of the associated incident (required).
            email: Recipient email address; must belong to an existing user (required).
            type: Notification type (alert, update, reminder, report, solution_proposal,
                other); defaults to 'other'.
            status: Notification status (queued, sent, delivered, opened, failed); defaults
                to 'queued'.
            subject: Subject of the notification.
            message: Message content of the notification.

        Returns:
            The created notification.
        """
        self._require_incident(incident_id)
        self._require_email_user(email)
        acting_email = self._acting_email()
        if acting_email is not None and email == acting_email:
            raise ItsmError(
                "Cannot send notification to yourself",
                code="CANNOT_SEND_TO_SELF",
                field="email",
            )

        notification_id, _ = self._make_id(self.db.notification, "NOTIF")
        now = self._now()
        notification = Notification(
            notification_id=notification_id,
            incident_id=incident_id,
            org_id=self._acting_org(),
            email=email,
            subject=subject,
            message=message,
            type=type or "other",
            status=status or "queued",
            created_on=now,
            updated_on=now,
        )
        self.db.notification[notification_id] = notification
        return notification

    @is_tool(ToolType.WRITE)
    def update_notification(
        self,
        notification_id: str,
        incident_id: Optional[str] = None,
        email: Optional[str] = None,
        type: Optional[str] = None,
        status: Optional[str] = None,
        subject: Optional[str] = None,
        message: Optional[str] = None,
    ) -> Notification:
        """Update an existing notification. Only the fields you pass are changed.

        Args:
            notification_id: Id of the notification to update (required).
            incident_id: New associated incident id; validated for existence if supplied.
            email: New recipient email; must belong to an existing user if supplied.
            type: New notification type (alert, update, reminder, report,
                solution_proposal, other).
            status: New notification status (queued, sent, delivered, opened, failed).
            subject: New subject.
            message: New message content.

        Returns:
            The updated notification.
        """
        notification = self._require_notification(notification_id)
        if incident_id is not None:
            self._require_incident(incident_id)
        if email is not None:
            self._require_email_user(email)

        updates = {
            "incident_id": incident_id,
            "email": email,
            "type": type,
            "status": status,
            "subject": subject,
            "message": message,
        }
        for field, value in updates.items():
            if value is not None:
                setattr(notification, field, value)
        notification.updated_on = self._now()
        return notification

    @is_tool(ToolType.WRITE)
    def delete_notifications(self, notification_id: str) -> dict:
        """Delete a notification by id.

        Note: the upstream MCP registers this tool but does not wire a router endpoint for it,
        so it never deletes anything and the server returns an "API endpoint not found" error.
        This port mirrors that behaviour exactly (raises; no state change).

        Args:
            notification_id: The id of the notification to delete (e.g. 'NOTIF_001').

        Returns:
            A success message with the deleted notification id (never reached: see note).
        """
        raise ItsmError(
            "API endpoint not found for tool: delete_notifications. "
            "Check that router function name matches tool name.",
            code="API_ENDPOINT_NOT_FOUND",
        )

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_notifications(
        self,
        notification_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        email: Optional[str] = None,
        type: Optional[str] = None,
        status: Optional[str] = None,
        created_before: Optional[str] = None,
        created_after: Optional[str] = None,
    ) -> dict:
        """Search notifications using various filters; all are optional and ANDed together.

        Empty-string or null values for any filter are ignored. Date filters compare against
        ``created_on``: ``created_after`` is exclusive (> value) and ``created_before`` is
        inclusive (<= value).

        Args:
            notification_id: Filter by notification id.
            incident_id: Filter by associated incident id.
            email: Filter by recipient email address.
            type: Filter by notification type (alert, update, reminder, report,
                solution_proposal, other).
            status: Filter by notification status (queued, sent, delivered, opened, failed).
            created_before: Only notifications created on/before this ISO timestamp.
            created_after: Only notifications created strictly after this ISO timestamp.

        Returns:
            A mapping with the matching notifications and their count
            ({'notifications': [...], 'count': N}).
        """
        eq_filters = {
            "notification_id": notification_id,
            "incident_id": incident_id,
            "email": email,
            "type": type,
            "status": status,
        }
        active = {k: v for k, v in eq_filters.items() if v}
        out: List[Notification] = []
        for notif in self.db.notification.values():
            if any(getattr(notif, attr) != val for attr, val in active.items()):
                continue
            if created_after and (notif.created_on or "") <= created_after:
                continue
            if created_before and (notif.created_on or "") > created_before:
                continue
            out.append(notif)
        return {"notifications": out, "count": len(out)}

    @is_tool(ToolType.READ)
    def find_notifications_for_email(self, email: str) -> dict:
        """Retrieve notifications sent to a specific email address.

        Args:
            email: Email address to search for.

        Returns:
            A mapping with the matching notifications and their count
            ({'notifications': [...], 'count': N}).
        """
        out = [n for n in self.db.notification.values() if n.email == email]
        if not out:
            raise ItsmError(
                f"Notifications not found with identifier 'email={email}'",
                code="RESOURCE_NOT_FOUND",
                field=None,
            )
        return {"notifications": out, "count": len(out)}

    @is_tool(ToolType.READ)
    def find_notifications_sent_for_incident(self, incident_id: str) -> dict:
        """Retrieve notifications related to a specific incident.

        Args:
            incident_id: Incident id to search for.

        Returns:
            A mapping with the matching notifications and their count
            ({'notifications': [...], 'count': N}).
        """
        out = [n for n in self.db.notification.values() if n.incident_id == incident_id]
        if not out:
            raise ItsmError(
                f"Notifications not found with identifier 'incident_id={incident_id}'",
                code="RESOURCE_NOT_FOUND",
                field=None,
            )
        return {"notifications": out, "count": len(out)}
