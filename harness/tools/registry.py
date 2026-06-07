"""Tool registry: schema advertisement, validation and dispatch (spec §7).

Plugin modules register their callables here; the agent loop asks for the
OpenAI-shaped schemas and calls tools by name with JSON arguments.  Validation
is intentionally light (presence + coarse type of required params) so a model
that fluffs an argument gets a useful ``error:`` string back instead of a crash,
matching the loop's try/except contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional


class SchemaError(ValueError):
    """Raised when tool arguments do not satisfy the declared schema."""


_PY_TYPES = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any]
    permissions: tuple[str, ...] = ()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    # -- registration -------------------------------------------------- #
    def add(self, name: str, description: str, parameters: dict,
            fn: Callable[..., Any], permissions: tuple[str, ...] = ()) -> None:
        self._tools[name] = Tool(name, description, parameters, fn, permissions)

    def tool(self, name: str, description: str, parameters: dict,
             permissions: tuple[str, ...] = ()):
        """Decorator form."""
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.add(name, description, parameters, fn, permissions)
            return fn
        return deco

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    # -- introspection ------------------------------------------------- #
    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def schemas(self, names: Optional[list[str]] = None) -> list[dict]:
        keys = names if names is not None else list(self._tools)
        return [self._tools[k].schema() for k in keys if k in self._tools]

    # -- validation + dispatch ---------------------------------------- #
    def validate(self, name: str, arguments: Any) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            raise SchemaError(f"unknown tool: {name}")
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments or "{}")
            except json.JSONDecodeError as e:
                raise SchemaError(f"arguments are not valid JSON: {e}") from e
        else:
            args = dict(arguments or {})

        schema = tool.parameters or {}
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in args:
                raise SchemaError(f"missing required parameter: {req}")
        for key, val in args.items():
            spec = props.get(key)
            if not spec:
                continue
            expected = spec.get("type")
            py = _PY_TYPES.get(expected)
            if py and val is not None and not isinstance(val, py):
                # allow ints where numbers expected, etc.; only flag clear mismatches
                if not (expected == "number" and isinstance(val, (int, float))):
                    raise SchemaError(
                        f"parameter '{key}' expected {expected}, got {type(val).__name__}")
        return args

    def call(self, name: str, arguments: Any) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"error: unknown tool '{name}'"
        try:
            args = self.validate(name, arguments)
            result = tool.fn(**args)
        except SchemaError as e:
            return f"error: {e}"
        except Exception as e:  # noqa: BLE001 — tool failures must not kill the loop
            return f"error: tool '{name}' raised {type(e).__name__}: {e}"
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            return str(result)


# Process-wide registry.
registry = ToolRegistry()
