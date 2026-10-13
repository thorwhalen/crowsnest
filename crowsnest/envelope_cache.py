"""A cached openloops envelope: asked for at most once per ``every``, read by the page.

The report never fetches (:mod:`crowsnest.report` renders what it is handed), and the two
registers that come from openloops -- *Owed* (:mod:`crowsnest.owed`) and *Free to proceed*
(:mod:`crowsnest.blocked`) -- call GitHub. So each keeps its envelope in a file under the
data directory and :func:`refresh` asks again only when the file is older than ``every``.

"Could not look" is never "nothing there", at any step:

- an envelope whose listing failed (``listed: false``) is kept as it is, so the page says
  the list is unavailable; and it is not fresh, so the next run asks again;
- a lister that raises (``gh`` missing, openloops not importable) leaves the cache as it
  was, flagged ``refresh_error`` so the page says the refresh failed, or, with no cache
  yet, becomes an unlisted envelope carrying the reason.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = ["DFLT_EVERY", "cache_path", "load", "refresh"]

#: How old a cached envelope may get before :func:`refresh` asks openloops again.
DFLT_EVERY = timedelta(minutes=10)

Lister = Callable[..., Mapping]


def cache_path(path: str | Path | None, *, name: str) -> Path:
    """Where an envelope is kept: ``path``, else ``<data dir>/<name>``."""
    if path:
        return Path(path).expanduser()
    from crowsnest.paths import data_dir

    return data_dir() / name


def _when(text) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def load(path: str | Path | None, *, name: str) -> dict | None:
    """The cached envelope, or ``None`` when there is none (or it cannot be read)."""
    try:
        doc = json.loads(cache_path(path, name=name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def refresh(
    *,
    name: str,
    ask: Callable[[], Mapping],
    path: str | Path | None = None,
    now: datetime | None = None,
    every: timedelta = DFLT_EVERY,
) -> dict:
    """The envelope the page will read: the cache while it is fresh, else ``ask()``'s.

    ``ask`` is a thunk over the lister, so each register decides its own keyword
    arguments (``verify=False``, a limit). It is called inside the ``try``: anything that
    goes wrong reaching openloops is the register's reason, not the page's failure.
    """
    now = datetime.now(timezone.utc) if now is None else now
    cached = load(path, name=name)
    then = _when(cached.get("fetched_at")) if cached else None
    if cached and cached.get("listed", True) and then and now - then < every:
        return cached
    try:
        envelope = dict(ask())
    except Exception as exc:  # noqa: BLE001 -- openloops or gh failing must not fail the page
        reason = f"{type(exc).__name__}: {exc}".strip(": ")
        if cached and cached.get("listed", True):
            return {**cached, "refresh_error": reason}
        return {"listed": False, "error": reason, "rows": []}
    envelope["fetched_at"] = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    target = cache_path(path, name=name)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(envelope, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)
    return envelope
