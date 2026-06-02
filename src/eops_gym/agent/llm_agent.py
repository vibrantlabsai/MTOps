"""Minimal litellm tool-calling agent.

This is a default/demo stand-in for the full action-space agent (item 1, out of
scope). It is good enough to drive the tools during an eval run: it follows the
domain policy, makes one tool call at a time, and produces a closing summary.
"""

from dataclasses import dataclass, field
from typing import Optional

from eops_gym.data_model.message import Message, SystemMessage
from eops_gym.utils.llm_utils import generate

AGENT_SYSTEM = """
You are an enterprise-operations support agent. Help the user by following the
policy below and using the available tools. Make one tool call at a time and use
the tool results to decide the next step. Use exact record identifiers returned
by the tools (e.g. user/group ids), not display names. When the user's request
is fully handled, reply with a short summary of what you changed.

{policy}
""".strip()


@dataclass
class AgentState:
    messages: list[Message] = field(default_factory=list)


class LLMAgent:
    def __init__(
        self,
        policy: str,
        tool_schemas: list[dict],
        llm: str,
        llm_args: Optional[dict] = None,
    ):
        self.system = SystemMessage(content=AGENT_SYSTEM.format(policy=policy))
        self.tool_schemas = tool_schemas
        self.llm = llm
        self.llm_args = llm_args if llm_args is not None else {"temperature": 0.0, "max_tokens": 4096}

    def get_init_state(self) -> AgentState:
        return AgentState(messages=[self.system])

    def generate_next_message(self, message: Message, state: AgentState):
        state.messages.append(message)
        resp = generate(
            model=self.llm,
            messages=state.messages,
            tools=self.tool_schemas,
            **self.llm_args,
        )
        state.messages.append(resp)
        return resp, state
