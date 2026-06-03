"""Default LLM configuration for the user simulator and NL-assertion judge.

Models are litellm provider strings; override per run via the CLI flags or env
vars. Defaults use OpenAI so a run works with just ``OPENAI_API_KEY`` set.
"""

# max_tokens must be generous enough that reasoning models (which spend tokens on hidden
# chain-of-thought) can finish reasoning AND still emit their reply/JSON. Too small a budget
# truncates them mid-reasoning (finish_reason=length, empty content). 4096 mirrors the original.
DEFAULT_MAX_TOKENS = 4096

DEFAULT_LLM_USER = "gpt-4o-mini"
DEFAULT_LLM_USER_ARGS = {"temperature": 0.7, "max_tokens": DEFAULT_MAX_TOKENS}

DEFAULT_LLM_NL_JUDGE = "gpt-4o-mini"
DEFAULT_LLM_NL_JUDGE_ARGS = {"temperature": 0.0, "max_tokens": DEFAULT_MAX_TOKENS}
