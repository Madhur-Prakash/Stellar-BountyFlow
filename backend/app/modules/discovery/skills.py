"""Skill name normalisation (pure functions, no I/O).

Bounties, tags and profiles are free text, so "JS", "javascript" and "Java Script" must meet in one graph node.
``normalize_skill`` lower-cases, trims and collapses whitespace like the tag validator, then looks the name up by a
separator-insensitive key ("smart-contracts", "smart_contracts" and "smart contracts" are one key) in the alias
table below. Unknown names keep their own spelling with separators turned into single spaces.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_SKILL_LENGTH = 40

_WHITESPACE = re.compile(r"\s+")
_SEPARATORS = re.compile(r"[\s_\-]+")

# Canonical name -> spellings that mean the same skill. Canonical names are the forms most bounties use.
_CANONICAL: dict[str, tuple[str, ...]] = {
    "javascript": ("js", "java script", "ecmascript", "es6", "vanilla js"),
    "typescript": ("ts", "type script"),
    "python": ("py", "python3", "python 3"),
    "go": ("golang", "go lang"),
    "rust": ("rustlang", "rust lang"),
    "node.js": ("node", "nodejs", "node js"),
    "react": ("react.js", "reactjs", "react js"),
    "react native": ("react-native", "reactnative", "rn"),
    "next.js": ("next", "nextjs", "next js"),
    "vue": ("vue.js", "vuejs", "vue js"),
    "postgresql": ("postgres", "psql", "pg", "postgre sql"),
    "kubernetes": ("k8s", "kube"),
    "tailwind": ("tailwindcss", "tailwind css"),
    "css": ("css3",),
    "html": ("html5",),
    "c++": ("cpp", "cplusplus"),
    "c#": ("csharp", "c sharp"),
    "graphql": ("gql", "graph ql"),
    "webassembly": ("wasm", "web assembly"),
    "soroban": ("soroban sdk", "soroban smart contracts", "soroban contracts"),
    "stellar": ("stellar sdk", "stellar network", "xlm"),
    "smart contracts": ("smart contract", "smartcontracts", "smartcontract"),
    "security": ("sec", "appsec", "application security", "infosec"),
    "documentation": ("docs", "technical writing", "tech writing"),
    "internationalization": ("i18n", "internationalisation"),
    "localization": ("l10n", "localisation"),
    "machine learning": ("ml",),
    "devops": ("dev ops",),
    "ci/cd": ("ci", "cicd", "ci cd", "continuous integration"),
    "frontend": ("front end", "frontend development"),
    "backend": ("back end", "backend development"),
    "full stack": ("fullstack", "full stack development"),
    "ui design": ("ui", "user interface design"),
    "ux research": ("user research", "ux researcher"),
    "figma": ("figma design",),
    "aws": ("amazon web services",),
    "google cloud": ("gcp", "google cloud platform"),
    "docker": ("docker compose",),
    "kafka": ("apache kafka",),
}


def _key(value: str) -> str:
    return _SEPARATORS.sub(" ", value).strip()


_ALIASES: dict[str, str] = {}
for _canonical, _spellings in _CANONICAL.items():
    _ALIASES[_key(_canonical)] = _canonical
    for _spelling in _spellings:
        _ALIASES[_key(_spelling)] = _canonical


def normalize_skill(raw: str) -> str:
    """Canonical graph name for one skill or tag ("" for blank input)."""
    value = _WHITESPACE.sub(" ", raw.strip().lower()).strip(" #.,;:")[:MAX_SKILL_LENGTH]
    if not value:
        return ""
    key = _key(value)
    return _ALIASES.get(key, key)


def normalize_all(values: Iterable[str]) -> list[str]:
    """Canonical names, deduplicated, in first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        name = normalize_skill(value)
        if name:
            seen.setdefault(name, None)
    return list(seen)


def match_keys(canonical_names: Iterable[str]) -> list[str]:
    """Separator-insensitive keys of every known spelling of these skills, for SQL prefilters that compare
    ``regexp_replace(lower(name), '[\\s_-]+', ' ')`` against them."""
    keys: dict[str, None] = {}
    for name in canonical_names:
        for spelling in (name, *_CANONICAL.get(name, ())):
            keys.setdefault(_key(spelling), None)
    return list(keys)
