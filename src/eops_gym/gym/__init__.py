"""Gymnasium-compatible RL/training interface for EnterpriseOps Gym.

Requires the optional ``gymnasium`` dependency: ``uv pip install -e ".[gym]"``.
"""

from eops_gym.gym.gym_agent import (
    EOPS_ENV_ID,
    AgentGymEnv,
    GymAgent,
    parse_action_string,
    register_gym_agent,
)

__all__ = [
    "EOPS_ENV_ID",
    "AgentGymEnv",
    "GymAgent",
    "parse_action_string",
    "register_gym_agent",
]
