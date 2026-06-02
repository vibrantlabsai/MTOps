"""Task and evaluation-criteria models (items 6 + 7).

Mirrors tau2's ``data_model/tasks.py`` but trimmed to what items 4-7 need:
a user scenario (persona + task description), evaluation criteria (gold actions
+ NL assertions), and a per-task initial-state ``Delta`` (item 7).
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from eops_gym.environment.delta import Delta


class UserProfile(BaseModel):
    """The persona the user simulator role-plays (item 4 input)."""

    name: str
    personality: str


class UserScenario(BaseModel):
    """Everything passed to the user simulator."""

    persona: UserProfile
    task_description: str


class Action(BaseModel):
    """A gold tool call replayed to compute the expected DB state (item 6)."""

    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class EvaluationCriteria(BaseModel):
    """How a task is scored: gold actions (DB-hash), NL assertions, and/or SQL verifiers.

    ``verifiers`` are the original benchmark's ``database_state`` checks
    (``{query, expected_value, comparison_type}``); scoring against them is directly
    comparable to the original EnterpriseOps leaderboard.
    """

    actions: List[Action] = Field(default_factory=list)
    nl_assertions: List[str] = Field(default_factory=list)
    verifiers: List[Dict[str, Any]] = Field(default_factory=list)


class Task(BaseModel):
    """A single benchmark task (items 6 + 7)."""

    id: str
    user_scenario: UserScenario
    evaluation_criteria: EvaluationCriteria = Field(default_factory=EvaluationCriteria)
    # item 7: collection -> record_id -> {set|create|delete}
    initial_state_delta: Optional[Delta] = None
    # Domain runtime context: which seed db to load and the authenticated caller, e.g.
    # {"seed": "seed_main", "acting_user_id": "USER_001"}.
    environment: Optional[Dict[str, Any]] = None
    # Optional oracle-mode tool subset exposed to the agent (mirrors the original benchmark's
    # selected_tools); when None the agent sees the full domain toolset.
    selected_tools: Optional[List[str]] = None
