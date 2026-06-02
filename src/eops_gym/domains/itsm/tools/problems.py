"""Problem tools (5) — faithful port of the ITSM MCP's problem category.

Covers problem CRUD/search plus the assignment lookup. Verified against the live MCP by the
differential conformance test.

Key behaviours confirmed against the oracle:
- ``problem_id`` = ``PRB_<maxidseq+1:03d>`` (sequential on existing ids).
- ``number`` = ``PRB<maxnumberseq+1:07d>`` — derived from the max numeric tail across existing
  ``number`` values, NOT from the id sequence (seed rows may share a number).
- ``opened_by``/``org_id`` are inherited from the acting (authenticated) user on create.
- FK args (assigned_to/opened_by → users, assignment_group → group, configuration_item → ci,
  service, service_offering, original_task → incident) are validated.
- ``list_problems`` enum filters (status/category/impact/urgency/priority) match
  case-insensitively; id/text filters match exactly (case-sensitive); the text filters
  (problem_statement/short_description/worknotes/workaround/fix_notes) are case-insensitive
  substring matches. ``created_after`` is strict ``>``; ``created_before`` is ``<=``.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.data_model import Problem
from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool

# Enum-typed columns: the MCP filters these case-insensitively.
_ENUM_FILTERS = {"status", "category", "impact", "urgency", "priority"}


class ProblemToolsMixin(ItsmToolsBase):
    """Problem management tools."""

    # ----------------------------------------------------------- helpers
    def _prb_require_service(self, service_id: Optional[str], field: str = "service") -> None:
        if service_id is not None and service_id not in self.db.service:
            raise ItsmError(
                f"Service with ID '{service_id}' not found", code="INVALID_REFERENCE", field=field
            )

    def _prb_require_service_offering(
        self, offering_id: Optional[str], field: str = "service_offering"
    ) -> None:
        if offering_id is not None and offering_id not in self.db.service_offering:
            raise ItsmError(
                f"Service offering with ID '{offering_id}' not found",
                code="INVALID_REFERENCE", field=field,
            )

    def _next_problem_number(self) -> str:
        """Return the next problem ``number`` (``PRB<seq:07d>``).

        Sequence = max numeric tail across existing ``number`` values + 1 (1 if none).
        """
        seqs = []
        for prob in self.db.problem.values():
            num = prob.number or ""
            tail = num[3:] if num.startswith("PRB") else num
            if tail.isdigit():
                seqs.append(int(tail))
        nxt = (max(seqs) + 1) if seqs else 1
        return f"PRB{nxt:07d}"

    def _validate_problem_fks(
        self,
        opened_by: Optional[str] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        configuration_item: Optional[str] = None,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        original_task: Optional[str] = None,
    ) -> None:
        self._require_user(opened_by, "opened_by")
        self._require_user(assigned_to, "assigned_to")
        self._require_group(assignment_group)
        self._require_ci(configuration_item)
        self._prb_require_service(service)
        self._prb_require_service_offering(service_offering)
        if original_task is not None:
            self._require_incident(original_task, "original_task")

    # ------------------------------------------------------------------ writes
    @is_tool(ToolType.WRITE)
    def create_problem(
        self,
        problem_statement: str,
        status: str,
        impact: str,
        urgency: str,
        priority: str,
        short_description: Optional[str] = None,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        original_task: Optional[str] = None,
        category: Optional[str] = None,
        worknotes: Optional[str] = None,
        workaround: Optional[str] = None,
        fix_notes: Optional[str] = None,
    ) -> Problem:
        """Create a new problem record.

        ``problem_id`` (PRB_NNN) and ``number`` (PRB0000NNN) are auto-generated. The opener and
        organization are inherited from the acting user.

        Args:
            problem_statement: Detailed problem statement (required).
            status: Problem status: new, assess, root_cause, fix_in_progress, resolved, closed (required).
            impact: Impact level: high, medium, low (required).
            urgency: Urgency level: high, medium, low (required).
            priority: Priority level: critical, high, moderate, low, planning (required).
            short_description: Short description (max 255 chars).
            service: Service id.
            service_offering: Service offering id.
            configuration_item: Configuration item id.
            assigned_to: User id assigned to.
            assignment_group: Group id assigned to.
            original_task: Original incident id.
            category: Problem category: network, software, hardware, database.
            worknotes: Work notes.
            workaround: Workaround description.
            fix_notes: Fix notes.

        Returns:
            The created problem.
        """
        opened_by = self.acting_user_id
        self._validate_problem_fks(
            opened_by=opened_by, assigned_to=assigned_to, assignment_group=assignment_group,
            configuration_item=configuration_item, service=service,
            service_offering=service_offering, original_task=original_task,
        )

        problem_id, _ = self._make_id(self.db.problem, "PRB")
        now = self._now()
        problem = Problem(
            problem_id=problem_id,
            number=self._next_problem_number(),
            problem_statement=problem_statement,
            short_description=short_description,
            opened_by=opened_by,
            service=service,
            service_offering=service_offering,
            configuration_item=configuration_item,
            assigned_to=assigned_to,
            assignment_group=assignment_group,
            original_task=original_task,
            org_id=self._acting_org(),
            status=status,
            category=category,
            worknotes=worknotes,
            workaround=workaround,
            fix_notes=fix_notes,
            impact=impact,
            urgency=urgency,
            priority=priority,
            created_on=now,
            updated_on=now,
        )
        self.db.problem[problem_id] = problem
        return problem

    @is_tool(ToolType.WRITE)
    def update_problem(
        self,
        problem_id: Optional[str] = None,
        number: Optional[str] = None,
        opened_by: Optional[str] = None,
        problem_statement: Optional[str] = None,
        short_description: Optional[str] = None,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        original_task: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        worknotes: Optional[str] = None,
        workaround: Optional[str] = None,
        fix_notes: Optional[str] = None,
        impact: Optional[str] = None,
        urgency: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> Problem:
        """Update an existing problem identified by ``problem_id`` or ``number``.

        Only the fields you pass are changed. Raises an error if neither identifier is given or
        if no update fields are provided.

        Args:
            problem_id: Problem id (e.g. PRB_001). Use either this or 'number'.
            number: Problem number (e.g. PRB0000001). Use either this or 'problem_id'.
            opened_by: User id who opened the problem.
            problem_statement: Detailed problem statement.
            short_description: Short description.
            service: Service id.
            service_offering: Service offering id.
            configuration_item: Configuration item id.
            assigned_to: User id assigned to.
            assignment_group: Group id assigned to.
            original_task: Original incident id.
            status: Problem status: new, assess, root_cause, fix_in_progress, resolved, closed.
            category: Problem category: network, software, hardware, database.
            worknotes: Work notes.
            workaround: Workaround description.
            fix_notes: Fix notes.
            impact: Impact level: high, medium, low.
            urgency: Urgency level: high, medium, low.
            priority: Priority level: critical, high, moderate, low, planning.

        Returns:
            The updated problem.
        """
        if problem_id is None and number is None:
            raise ItsmError(
                "Either 'problem_id' or 'number' must be provided to identify the problem"
            )

        problem = self._find_problem(problem_id, number)

        updates = {
            "opened_by": opened_by, "problem_statement": problem_statement,
            "short_description": short_description, "service": service,
            "service_offering": service_offering, "configuration_item": configuration_item,
            "assigned_to": assigned_to, "assignment_group": assignment_group,
            "original_task": original_task, "status": status, "category": category,
            "worknotes": worknotes, "workaround": workaround, "fix_notes": fix_notes,
            "impact": impact, "urgency": urgency, "priority": priority,
        }
        active = {k: v for k, v in updates.items() if v is not None}
        if not active:
            raise ItsmError("No fields provided for update")

        self._validate_problem_fks(
            opened_by=opened_by, assigned_to=assigned_to, assignment_group=assignment_group,
            configuration_item=configuration_item, service=service,
            service_offering=service_offering, original_task=original_task,
        )

        for field, value in active.items():
            setattr(problem, field, value)
        problem.updated_on = self._now()
        return problem

    def _find_problem(
        self, problem_id: Optional[str], number: Optional[str]
    ) -> Problem:
        """Resolve a problem by id (preferred) or number; raise if not found."""
        if problem_id is not None:
            problem = self.db.problem.get(problem_id)
            if problem is None:
                raise ItsmError(
                    f"Problem with problem_id '{problem_id}' not found", field="problem_id"
                )
            return problem
        for problem in self.db.problem.values():
            if problem.number == number:
                return problem
        raise ItsmError(f"Problem with number '{number}' not found", field="number")

    # ------------------------------------------------------------------ reads
    @is_tool(ToolType.READ)
    def find_problem_by_number(self, number: str) -> Problem:
        """Find a problem by its unique problem number.

        Args:
            number: Problem number, e.g. 'PRB0000001'.

        Returns:
            The matching problem.
        """
        for problem in self.db.problem.values():
            if problem.number == number:
                return problem
        raise ItsmError(f"Problem with number '{number}' not found", field="number")

    @is_tool(ToolType.READ)
    def list_problems(
        self,
        problem_id: Optional[str] = None,
        number: Optional[str] = None,
        service: Optional[str] = None,
        service_offering: Optional[str] = None,
        configuration_item: Optional[str] = None,
        opened_by: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        problem_statement: Optional[str] = None,
        short_description: Optional[str] = None,
        impact: Optional[str] = None,
        urgency: Optional[str] = None,
        priority: Optional[str] = None,
        assigned_to: Optional[str] = None,
        assignment_group: Optional[str] = None,
        worknotes: Optional[str] = None,
        workaround: Optional[str] = None,
        fix_notes: Optional[str] = None,
        original_task: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> dict:
        """List problems, optionally filtered. All filters are ANDed; omitted filters ignored.

        Enum filters (status, category, impact, urgency, priority) match case-insensitively.
        Text filters (problem_statement, short_description, worknotes, workaround, fix_notes)
        are case-insensitive substring matches. All other filters are exact (case-sensitive).

        Args:
            problem_id: Filter by problem id (exact).
            number: Filter by number (exact).
            service: Filter by service id (exact).
            service_offering: Filter by service offering id (exact).
            configuration_item: Filter by configuration item id (exact).
            opened_by: Filter by user who opened (exact).
            status: Filter by status (case-insensitive).
            category: Filter by category (case-insensitive).
            problem_statement: Filter by problem statement (partial).
            short_description: Filter by short description (partial).
            impact: Filter by impact (case-insensitive).
            urgency: Filter by urgency (case-insensitive).
            priority: Filter by priority (case-insensitive).
            assigned_to: Filter by assigned user (exact).
            assignment_group: Filter by assigned group (exact).
            worknotes: Filter by worknotes (partial).
            workaround: Filter by workaround (partial).
            fix_notes: Filter by fix notes (partial).
            original_task: Filter by original incident id (exact).
            created_after: Only problems created strictly after this ISO timestamp.
            created_before: Only problems created on/before this ISO timestamp.

        Returns:
            A dict with 'problems' (the matching problems) and 'total_count'.
        """
        exact_filters = {
            "problem_id": problem_id, "number": number, "service": service,
            "service_offering": service_offering, "configuration_item": configuration_item,
            "opened_by": opened_by, "assigned_to": assigned_to,
            "assignment_group": assignment_group, "original_task": original_task,
        }
        enum_filters = {
            "status": status, "category": category, "impact": impact,
            "urgency": urgency, "priority": priority,
        }
        partial_filters = {
            "problem_statement": problem_statement, "short_description": short_description,
            "worknotes": worknotes, "workaround": workaround, "fix_notes": fix_notes,
        }
        exact = {k: v for k, v in exact_filters.items() if v is not None}
        enum = {k: v for k, v in enum_filters.items() if v is not None}
        partial = {k: v for k, v in partial_filters.items() if v is not None}

        out: List[Problem] = []
        for problem in self.db.problem.values():
            if any(getattr(problem, attr) != val for attr, val in exact.items()):
                continue
            if any(
                (getattr(problem, attr) or "").lower() != val.lower()
                for attr, val in enum.items()
            ):
                continue
            if any(
                val.lower() not in (getattr(problem, attr) or "").lower()
                for attr, val in partial.items()
            ):
                continue
            if created_after is not None and (problem.created_on or "") <= created_after:
                continue
            if created_before is not None and (problem.created_on or "") > created_before:
                continue
            out.append(problem)
        return {"problems": out, "total_count": len(out)}

    @is_tool(ToolType.READ)
    def get_problems_assigned_to(
        self, assignment_group: Optional[str] = None, assigned_to: Optional[str] = None
    ) -> dict:
        """Get problems assigned to a specific user and/or group (ANDed).

        Args:
            assignment_group: Filter by assignment group id.
            assigned_to: Filter by assigned user id.

        Returns:
            A dict with 'problems' (the matching problems) and 'total_count'.
        """
        out: List[Problem] = []
        for problem in self.db.problem.values():
            if assignment_group is not None and problem.assignment_group != assignment_group:
                continue
            if assigned_to is not None and problem.assigned_to != assigned_to:
                continue
            out.append(problem)
        return {"problems": out, "total_count": len(out)}
