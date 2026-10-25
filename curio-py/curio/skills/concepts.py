"""Concept graph: which skills transfer to which, and what each app calls them.

Loaded from a small bundled JSON file (``concepts.json``). Concepts are keyed by
a canonical name; an app may call the same idea something else ("frames" in
figma is the canonical "layers"). Related concepts carry a 0..1 weight that says
how much knowing one helps with the other. Edges are undirected.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from curio.learning_contract import concept_key

DEFAULT_GRAPH_PATH = Path(__file__).with_name("concepts.json")

_VERSION_SUFFIX_RE = re.compile(r"(\s+(cc|20\d\d|v?\d+(\s\d+)*))+$")


@dataclass(frozen=True, kw_only=True)
class Concept:
    key: str
    names: Mapping[str, str] = field(default_factory=dict)  # app -> local name
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConceptGraph:
    """Immutable lookup tables. Build with ``load()`` or ``from_dict()``."""

    concepts: Mapping[str, Concept]
    edges: Mapping[str, Mapping[str, float]]
    app_aliases: Mapping[str, str] = field(default_factory=dict)
    _by_name: Mapping[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _by_alias: Mapping[str, str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: Path = DEFAULT_GRAPH_PATH) -> ConceptGraph:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def empty(cls) -> ConceptGraph:
        return cls.from_dict({})

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ConceptGraph:
        app_aliases = {
            concept_key(k): concept_key(v) for k, v in raw.get("apps", {}).items()
        }
        concepts: dict[str, Concept] = {}
        by_name: dict[tuple[str, str], str] = {}
        by_alias: dict[str, str] = {}
        for raw_key, spec in raw.get("concepts", {}).items():
            key = concept_key(raw_key)
            names = {
                concept_key(app): concept_key(name) for app, name in spec.get("names", {}).items()
            }
            aliases = tuple(concept_key(a) for a in spec.get("aliases", ()))
            concepts[key] = Concept(key=key, names=names, aliases=aliases)
            for alias in aliases:
                by_alias.setdefault(alias, key)
            for app, name in names.items():
                by_name[(app, name)] = key
        edges: dict[str, dict[str, float]] = {}
        for a, b, weight in raw.get("related", ()):
            a, b, w = concept_key(a), concept_key(b), max(0.0, min(1.0, float(weight)))
            if a == b:
                continue
            edges.setdefault(a, {})[b] = max(w, edges.get(a, {}).get(b, 0.0))
            edges.setdefault(b, {})[a] = max(w, edges.get(b, {}).get(a, 0.0))
        return cls(concepts, edges, app_aliases, by_name, by_alias)

    def app(self, app: str) -> str:
        """Normalise an app key: "adobe photoshop 2024" -> "photoshop"."""
        key = concept_key(app)
        if key in self.app_aliases:
            return self.app_aliases[key]
        stripped = _VERSION_SUFFIX_RE.sub("", key)
        return self.app_aliases.get(stripped, stripped)

    def canonical(self, app: str, concept: str) -> str:
        """Canonical concept for what ``app`` calls ``concept``."""
        name = concept_key(concept)
        app = self.app(app)
        if (app, name) in self._by_name:
            return self._by_name[(app, name)]
        if name in self.concepts:
            return name
        return self._by_alias.get(name, name)

    def canonical_all(self, app: str, concepts: Iterable[str]) -> tuple[str, ...]:
        """Canonical, de-duplicated, order kept, blanks dropped."""
        seen: dict[str, None] = {}
        for concept in concepts:
            key = self.canonical(app, concept)
            if key:
                seen.setdefault(key, None)
        return tuple(seen)

    def name_in(self, concept: str, app: str) -> str:
        """What ``app`` calls a canonical concept."""
        spec = self.concepts.get(concept)
        if spec is None:
            return concept
        return spec.names.get(self.app(app), concept)

    def related(self, concept: str) -> Mapping[str, float]:
        return self.edges.get(concept, {})
