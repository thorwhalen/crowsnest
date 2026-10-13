"""What the person owes their sessions: the open ``manual-task`` issues openloops lists.

Every terminal's status line says "30+ owed", and the page is where the person looks for
what to do, so it shows the same list (crowsnest#85): each issue, whose repository, how
old, and one tap to open it. It is openloops' list (:func:`openloops.tools.owed`), read
without running any issue's verify predicate: a scheduled page must never execute
commands that an issue's body names.

The page never fetches. :func:`refresh` writes openloops' envelope to a cache file under
the data directory, at most once per ``every``, and the page reads that file. An envelope
whose listing failed (``listed: false``) is kept as it is, so the page can say the list is
unavailable rather than show an empty one: "nothing owed" and "could not look" must not
read the same (:mod:`crowsnest.envelope_cache` keeps that rule for both openloops
registers).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path

from crowsnest import envelope_cache

__all__ = ["DFLT_EVERY", "DFLT_LIMIT", "cache_path", "load", "refresh"]

#: How old the cached list may get before :func:`refresh` asks openloops again.
DFLT_EVERY = envelope_cache.DFLT_EVERY

#: How many issues are listed at most.
DFLT_LIMIT = 200

#: The cache file's name under the data directory.
CACHE_NAME = "owed.json"

Lister = Callable[..., Mapping]


def cache_path(path: str | Path | None = None) -> Path:
    """Where the list is kept: ``path``, else ``<data dir>/owed.json``."""
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
    """Ask openloops for the owed list when the cache is older than ``every``; the
    envelope the page will read.

    ``lister`` is openloops' :func:`~openloops.tools.owed` by default, always called with
    ``verify=False``. A lister that raises -- or an openloops that cannot be imported --
    leaves the cache as it was, flagged ``refresh_error``, or is an unlisted envelope
    saying why when there is no cache.
    """

    def ask() -> Mapping:
        nonlocal lister
        if lister is None:
            from openloops.tools import owed as lister
        return lister(verify=False, limit=limit)

    return envelope_cache.refresh(
        name=CACHE_NAME, ask=ask, path=path, now=now, every=every
    )
