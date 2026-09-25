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
read the same.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = ["DFLT_EVERY", "DFLT_LIMIT", "cache_path", "load", "refresh"]

#: How old the cached list may get before :func:`refresh` asks openloops again.
DFLT_EVERY = timedelta(minutes=10)

#: How many issues are listed at most.
DFLT_LIMIT = 200

Lister = Callable[..., Mapping]


def cache_path(path: str | Path | None = None) -> Path:
    """Where the list is kept: ``path``, else ``<data dir>/owed.json``."""
    if path:
        return Path(path).expanduser()
    from crowsnest.paths import data_dir

    return data_dir() / "owed.json"


def _when(text) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def load(path: str | Path | None = None) -> dict | None:
    """The cached envelope, or ``None`` when there is none (or it cannot be read)."""
    try:
        doc = json.loads(cache_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def refresh(
    *,
    path: str | Path | None = None,
    lister: Lister | None = None,
    now: datetime | None = None,
    every: timedelta = DFLT_EVERY,
    limit: int = DFLT_LIMIT,
) -> dict | None:
    """Ask openloops for the owed list when the cache is older than ``every``; the
    envelope the page will read.

    ``lister`` is openloops' :func:`~openloops.tools.owed` by default, always called with
    ``verify=False``. A lister that raises leaves the cache as it was.
    """
    now = datetime.now(timezone.utc) if now is None else now
    cached = load(path)
    then = _when(cached.get("fetched_at")) if cached else None
    if then is not None and now - then < every:
        return cached
    if lister is None:
        from openloops.tools import owed as lister
    try:
        envelope = dict(lister(verify=False, limit=limit))
    except Exception:  # noqa: BLE001 -- openloops or gh failing must not fail the page
        return cached
    envelope["fetched_at"] = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    target = cache_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(envelope, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)
    return envelope
