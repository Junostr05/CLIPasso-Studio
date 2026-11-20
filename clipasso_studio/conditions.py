"""Declarative rules "enabled when …" of the parameters (``Param.enabled_if`` in settings_schema.py).

A rule is called with the settings like the lambdas it replaced (``rule(settings) -> bool``) and can be written as
JSON (``rule.to_json()``), so the Mac app evaluates the same rules. Their meaning, also for the Mac app:

- ``On(k)``: the value of ``k`` is truthy (Python's ``bool``: false, 0, 0.0, "", null and a missing key are not)
- ``Off(k)``: the opposite of ``On(k)``
- ``Eq(k, v, default)`` / ``Ne(k, v, default)``: the value of ``k`` (``default`` when the key is missing) is / is
  not ``v``
- ``Gt(k, n)``: the value of ``k`` as a number (0 when it is missing, null, 0 or "") is greater than ``n``
- ``Has(k, flag)``: ``flag`` occurs in the value of ``k`` as text ("" when it is missing)
- ``All(…)`` / ``AnyOf(…)``: all / at least one of the rules
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class Cond:
    def __call__(self, settings: dict) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def to_json(self) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class On(Cond):
    key: str

    def __call__(self, settings: dict) -> bool:
        return bool(settings.get(self.key))

    def to_json(self) -> dict:
        return {"op": "on", "key": self.key}


@dataclass(frozen=True)
class Off(Cond):
    key: str

    def __call__(self, settings: dict) -> bool:
        return not settings.get(self.key)

    def to_json(self) -> dict:
        return {"op": "off", "key": self.key}


@dataclass(frozen=True)
class Eq(Cond):
    key: str
    value: Any
    default: Any = None

    def __call__(self, settings: dict) -> bool:
        return settings.get(self.key, self.default) == self.value

    def to_json(self) -> dict:
        out = {"op": "eq", "key": self.key, "value": self.value}
        if self.default is not None:
            out["default"] = self.default
        return out


@dataclass(frozen=True)
class Ne(Cond):
    key: str
    value: Any
    default: Any = None

    def __call__(self, settings: dict) -> bool:
        return settings.get(self.key, self.default) != self.value

    def to_json(self) -> dict:
        out = {"op": "ne", "key": self.key, "value": self.value}
        if self.default is not None:
            out["default"] = self.default
        return out


@dataclass(frozen=True)
class Gt(Cond):
    key: str
    value: float

    def __call__(self, settings: dict) -> bool:
        return float(settings.get(self.key) or 0) > self.value

    def to_json(self) -> dict:
        return {"op": "gt", "key": self.key, "value": self.value}


@dataclass(frozen=True)
class Has(Cond):
    key: str
    value: str

    def __call__(self, settings: dict) -> bool:
        return self.value in str(settings.get(self.key, ""))

    def to_json(self) -> dict:
        return {"op": "has", "key": self.key, "value": self.value}


@dataclass(frozen=True, init=False)
class All(Cond):
    of: tuple

    def __init__(self, *rules: Cond):
        object.__setattr__(self, "of", tuple(rules))

    def __call__(self, settings: dict) -> bool:
        return all(rule(settings) for rule in self.of)

    def to_json(self) -> dict:
        return {"op": "all", "of": [rule.to_json() for rule in self.of]}


@dataclass(frozen=True, init=False)
class AnyOf(Cond):
    of: tuple

    def __init__(self, *rules: Cond):
        object.__setattr__(self, "of", tuple(rules))

    def __call__(self, settings: dict) -> bool:
        return any(rule(settings) for rule in self.of)

    def to_json(self) -> dict:
        return {"op": "any", "of": [rule.to_json() for rule in self.of]}
