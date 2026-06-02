"""Typed OpenAI tool-schema generation from a function's signature + docstring.

The scaffold previously emitted ``{"type": "string"}`` for every parameter. Real tool-calling
needs accurate types, enums, and required-field info so the agent fills arguments correctly.
This module derives an OpenAI ``function`` schema from a bound tool method's type hints and a
Google-style docstring (``Args:`` block), mirroring tau2's docstring-driven ``Tool`` schema.

Supported annotations: str, int, float, bool, Optional[X], list[X]/List[X], Literal[...],
and (best-effort) nested fall back to string.
"""

from __future__ import annotations

import inspect
import re
import typing
from typing import Any, Callable, Literal, Union, get_args, get_origin

_PRIMITIVES: dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    """If ``annotation`` is Optional[X]/Union[X, None], return (True, X); else (False, annotation)."""
    if get_origin(annotation) is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return True, args[0]
        return True, args[0] if args else annotation
    return False, annotation


def _json_schema_for(annotation: Any) -> dict[str, Any]:
    """Map a Python annotation to a JSON-schema fragment."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}

    optional, inner = _is_optional(annotation)
    annotation = inner

    origin = get_origin(annotation)
    if origin is Literal:
        values = list(get_args(annotation))
        elem_type = _PRIMITIVES.get(type(values[0]), "string") if values else "string"
        return {"type": elem_type, "enum": values}
    if origin in (list, typing.List):
        args = get_args(annotation)
        item = _json_schema_for(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item}
    if origin in (dict, typing.Dict):
        return {"type": "object"}
    if annotation in _PRIMITIVES:
        return {"type": _PRIMITIVES[annotation]}
    return {"type": "string"}


def _parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Return (description, {param: description}) from a Google-style docstring."""
    if not doc:
        return "", {}
    lines = inspect.cleandoc(doc).splitlines()
    # description = everything before the Args:/Returns:/Raises: section
    desc_lines: list[str] = []
    i = 0
    while i < len(lines) and not re.match(r"^(Args|Arguments|Returns|Raises):\s*$", lines[i].strip()):
        desc_lines.append(lines[i])
        i += 1
    description = "\n".join(desc_lines).strip()

    params: dict[str, str] = {}
    in_args = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^(Args|Arguments):\s*$", stripped):
            in_args = True
            continue
        if re.match(r"^(Returns|Raises):\s*$", stripped):
            in_args = False
            continue
        if in_args:
            m = re.match(r"^([A-Za-z_]\w*)\s*(?:\([^)]*\))?:\s*(.*)$", stripped)
            if m:
                params[m.group(1)] = m.group(2).strip()
    return description, params


def build_tool_schema(func: Callable, name: str | None = None) -> dict[str, Any]:
    """Build an OpenAI ``function`` tool schema for a (bound or unbound) tool method."""
    sig = inspect.signature(func)
    description, param_docs = _parse_docstring(func.__doc__)
    # Resolve string annotations (modules use ``from __future__ import annotations``, so
    # ``param.annotation`` would otherwise be a string and lose typing/enums).
    try:
        hints = typing.get_type_hints(func)
    except Exception:  # noqa: BLE001 - fall back to raw annotations if resolution fails
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname == "self" or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        annotation = hints.get(pname, param.annotation)
        schema = _json_schema_for(annotation)
        if pname in param_docs:
            schema["description"] = param_docs[pname]
        properties[pname] = schema
        is_optional, _ = _is_optional(annotation)
        if param.default is inspect.Parameter.empty and not is_optional:
            required.append(pname)

    fn_schema: dict[str, Any] = {
        "name": name or func.__name__,
        "description": description,
        "parameters": {"type": "object", "properties": properties},
    }
    if required:
        fn_schema["parameters"]["required"] = required
    return {"type": "function", "function": fn_schema}
