"""What is free to proceed (crowsnest#85): openloops' ``blocked_by`` edges, cached.

The sibling of :mod:`crowsnest.owed`, from :func:`openloops.tools.blocked`: each open issue
that waits on another, with every edge resolved, as ``unblocked`` (every blocker closed --
the work is free and nobody was told), ``blocked`` (naming what it waits on) or
``unknown`` (the edges could not be read). The page shows them as ``ready`` / ``waits`` /
``?`` and never rounds ``unknown`` into either.

Resolving an edge is one GitHub call per candidate (openloops bounds it at
:data:`DFLT_LIMIT`), so the page never fetches: :func:`refresh` writes the envelope to a
cache file under the data directory at most once per ``every``
(:mod:`crowsnest.envelope_cache`), and an envelope whose discovery failed is kept as it is,
so the page says it is unavailable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path

from crowsnest import envelope_cache

__all__ = ["DFLT_EVERY", "DFLT_LIMIT", "cache_path", "load", "refresh"]

#: How old the cached list may get before :func:`refresh` asks openloops again.
DFLT_EVERY = envelope_cache.DFLT_EVERY

#: How many candidate issues are resolved at most: one GitHub call each.
DFLT_LIMIT = 50

#: The cache file's name under the data directory.
CACHE_NAME = "blocked.json"

Lister = Callable[..., Mapping]


def cache_path(path: str | Path | None = None) -> Path:
    """Where the list is kept: ``path``, else ``<data dir>/blocked.json``."""
    return envelope_cache.cache_path(path, name=CACHE_NAME)


def load(path: str | Path | None = None) -> dict | None:
    """The cached envelope, or ``None`` when there is none (or it cannot be read)."""
    return envelope_cache.load(path, name=CACHE_NAME)


def refresh(
    *,
    path: str | Path | None = None,
    lister: Lister | None = None,
    now: datetime | None = None,
    every: timedelta = DFLT_EVERY,
    limit: int = DFLT_LIMIT,
) -> dict:
    """Ask openloops what is free to proceed when the cache is older than ``every``; the
    envelope the page will read.

    ``lister`` is openloops' :func:`~openloops.tools.blocked` by default, called with
    ``resolve=True`` (without it every row reads ``unknown``). A lister that raises -- or
    an openloops that cannot be imported -- leaves the cache as it was, flagged
    ``refresh_error``, or is an unlisted envelope saying why when there is no cache.
    """

    def ask() -> Mapping:
        nonlocal lister
        if lister is None:
            from openloops.tools import blocked as lister
        return lister(resolve=True, limit=limit)

    return envelope_cache.refresh(
        name=CACHE_NAME, ask=ask, path=path, now=now, every=every
    )
