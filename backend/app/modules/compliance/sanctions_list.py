"""Loading and parsing sanctions lists of Stellar addresses (pure parsing, plus file/URL loading).

Recognised formats, detected from the content:

* the OFAC SDN list (``sdn.csv`` or the XML exports): every ``Digital Currency Address - XLM <address>`` remark;
* a JSON array of addresses, or of objects with an ``address`` key;
* plain text: one address per line, ``#`` starts a comment, anything after the address on a line is ignored.

Only valid Stellar account ids (``G…``, checksum verified) are kept, so a malformed or truncated download never
turns into bogus entries.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from stellar_sdk import StrKey

from app.core.mainnet import resolve_path

# OFAC publishes crypto identifiers as "Digital Currency Address - <TICKER> <address>" in the SDN remarks.
_OFAC_XLM = re.compile(r"Digital Currency Address - XLM\s+([A-Z2-7]{56})")
_ADDRESS = re.compile(r"\bG[A-Z2-7]{55}\b")
MAX_LIST_BYTES = 64 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class LoadedList:
    source: str  # the file path or URL it came from
    addresses: frozenset[str]
    format: str  # "ofac-sdn" | "json" | "text"


def is_account_id(value: str) -> bool:
    return StrKey.is_valid_ed25519_public_key(value)


def parse(content: str) -> tuple[frozenset[str], str]:
    """Addresses in ``content`` and the detected format."""
    if "Digital Currency Address - " in content:
        return frozenset(a for a in _OFAC_XLM.findall(content) if is_account_id(a)), "ofac-sdn"
    stripped = content.lstrip()
    if stripped.startswith("["):
        try:
            items = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("the list looks like JSON but does not parse") from exc
        found: set[str] = set()
        for item in items if isinstance(items, list) else []:
            value = item.get("address") if isinstance(item, dict) else item
            if isinstance(value, str) and is_account_id(value.strip()):
                found.add(value.strip())
        return frozenset(found), "json"
    found = set()
    for line in content.splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        match = _ADDRESS.search(text)
        if match and is_account_id(match.group(0)):
            found.add(match.group(0))
    return frozenset(found), "text"


def _read_file(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_LIST_BYTES:
            raise ValueError(f"{path} is larger than {MAX_LIST_BYTES} bytes")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc.strerror or exc}") from exc


async def load(path: str | None, url: str | None) -> LoadedList | None:
    """Reads the configured list (the file wins when both are set). ``None`` when none is configured. Raises
    ``ValueError`` for an unreadable or unparseable source, so the caller keeps the entries it already has."""
    if path:
        resolved = resolve_path(path)
        content = await asyncio.to_thread(_read_file, resolved)
        source = str(resolved)
    elif url:
        if not url.startswith("https://"):
            raise ValueError("SANCTIONS_LIST_URL must be an https:// URL")
        try:
            async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
                response = await client.get(url, headers={"User-Agent": "bountyflow-sanctions-sync"})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"cannot download the sanctions list: {type(exc).__name__}") from exc
        if len(response.content) > MAX_LIST_BYTES:
            raise ValueError(f"the sanctions list is larger than {MAX_LIST_BYTES} bytes")
        content = response.text
        source = url
    else:
        return None
    addresses, fmt = parse(content)
    return LoadedList(source=source, addresses=addresses, format=fmt)
