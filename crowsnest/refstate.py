"""What a referenced issue or pull request is now: open or closed, and its title.

A row's references are resolved from text alone (:mod:`crowsnest.links` never fetches: a
page must not be hundreds of network calls). So what each one *is* now -- open, closed,
merged, and what it is called -- comes from a store that a scheduled refresh fills, and
the page only reads it. A state older than ``stale_after`` reads as unknown, and the page
claims nothing it does not know.

The store maps ``"owner/repo"`` to ``{"fetched_at", "items": {number: {"state", "title",
"closed_at"}}}``; by default one JSON file per repository under ``<data dir>/refs/``.
``fetch=`` is how a repository's issues and pull requests are listed, ``(owner, repo) ->
{number: item}``; by default the ``gh`` CLI, twice per repository (issues, then pull
requests). :func:`refresh` asks only for repositories whose state is older than
``every``, at most ``limit`` per call, so a once-a-minute job spreads the calls out.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crowsnest.links import github_ref

__all__ = [
    "DFLT_EVERY",
    "DFLT_LIMIT",
    "DFLT_STALE_AFTER",
    "dflt_store",
    "gh_fetch",
    "refresh",
    "repos_of",
    "state_of",
]

#: How old a repository's state may get before :func:`refresh` asks again.
DFLT_EVERY = timedelta(minutes=30)

#: How many repositories one :func:`refresh` asks about at most.
DFLT_LIMIT = 6

#: Past this age a state is not shown: the page says nothing rather than something old.
DFLT_STALE_AFTER = timedelta(hours=6)

#: How many issues and pull requests are listed per repository and kind.
LIST_LIMIT = 500

#: The kinds of reference that have a state.
KINDS = ("issue", "pr")

_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

Fetch = Callable[[str, str], Mapping[str, Mapping]]


class _DirStore(MutableMapping):
    """``"owner/repo"`` -> document, one JSON file per repository under ``root``."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()

    def _path(self, key: str) -> Path:
        owner, _, repo = str(key).partition("/")
        if not (_SEGMENT.match(owner) and _SEGMENT.match(repo)) or ".." in (owner, repo):
            raise KeyError(key)
        return self.root / owner / f"{repo}.json"

    def __getitem__(self, key: str) -> dict:
        try:
            doc = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise KeyError(key) from None
        if not isinstance(doc, dict):
            raise KeyError(key)
        return doc

    def __setitem__(self, key: str, doc: dict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)

    def __delitem__(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[str]:
        if not self.root.is_dir():
            return
        for path in sorted(self.root.glob("*/*.json")):
            yield f"{path.parent.name}/{path.stem}"

    def __len__(self) -> int:
        return sum(1 for _ in self)


def dflt_store(root: str | Path | None = None) -> MutableMapping[str, dict]:
    """One JSON file per repository under ``root`` (default ``<data dir>/refs``)."""
    if root is None:
        from crowsnest.paths import data_dir

        root = data_dir() / "refs"
    return _DirStore(root)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _when(text) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------------------
# Fetching


def _gh_list(kind: str, owner: str, repo: str) -> list[dict]:
    fields = "number,title,state,closedAt"
    argv = [
        "gh", kind, "list", "--repo", f"{owner}/{repo}", "--state", "all",
        "--limit", str(LIST_LIMIT), "--json", fields,
    ]  # fmt: skip
    done = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=60)
    if done.returncode:
        said = (done.stderr or done.stdout).strip().splitlines()
        raise ValueError(
            f"gh {kind} list {owner}/{repo}: {said[-1] if said else 'failed'}"
        )
    found = json.loads(done.stdout or "[]")
    return found if isinstance(found, list) else []


def gh_fetch(owner: str, repo: str) -> dict[str, dict]:
    """A repository's issues and pull requests by number, from the ``gh`` CLI."""
    if not shutil.which("gh"):
        raise ValueError("refreshing reference states needs the gh CLI on PATH")
    items: dict[str, dict] = {}
    for kind in ("issue", "pr"):
        for got in _gh_list(kind, owner, repo):
            number = str(got.get("number") or "")
            if not number.isdigit():
                continue
            items[number] = {
                "state": str(got.get("state") or "").lower(),
                "title": str(got.get("title") or ""),
                "closed_at": str(got.get("closedAt") or ""),
            }
    return items


# --------------------------------------------------------------------------------------
# Refreshing and reading


def repos_of(rows: Iterable[Mapping]) -> list[str]:
    """Every ``"owner/repo"`` a row's references point into, issues and pull requests only.

    >>> repos_of([{'links': [{'url': 'https://github.com/o/r/issues/3'},
    ...                      {'url': 'https://github.com/o/r/pull/4'},
    ...                      {'url': 'https://github.com/o/s/commit/abc'}]}])
    ['o/r']
    """
    found: set[str] = set()
    for row in rows:
        for link in row.get("links") or ():
            if not isinstance(link, Mapping):
                continue
            kind, owner, repo, number = github_ref(str(link.get("url") or ""))
            if kind in KINDS and number:
                found.add(f"{owner}/{repo}")
    return sorted(found)


def refresh(
    repos: Iterable[str],
    *,
    store: MutableMapping[str, dict] | None = None,
    fetch: Fetch | None = None,
    now: datetime | None = None,
    every: timedelta = DFLT_EVERY,
    limit: int = DFLT_LIMIT,
) -> dict:
    """Ask again about the repositories whose state is older than ``every``, oldest first,
    at most ``limit`` of them. One that cannot be listed keeps what the store had.

    Returns ``{"refreshed": [...], "failed": {repo: reason}, "fresh": n}``.
    """
    store = dflt_store() if store is None else store
    fetch = gh_fetch if fetch is None else fetch
    now = datetime.now(timezone.utc) if now is None else now
    due: list[tuple[datetime, str]] = []
    fresh = 0
    for key in sorted(set(repos)):
        try:
            then = _when(store[key].get("fetched_at"))
        except KeyError:
            then = None
        if then is not None and now - then < every:
            fresh += 1
            continue
        due.append((then or datetime.min.replace(tzinfo=timezone.utc), key))
    refreshed, failed = [], {}
    for _, key in sorted(due)[: max(0, limit)]:
        owner, _, repo = key.partition("/")
        try:
            items = fetch(owner, repo)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            failed[key] = str(exc)
            continue
        try:
            store[key] = {"fetched_at": _stamp(now), "items": dict(items)}
        except KeyError:
            failed[key] = "not a repository name"
            continue
        refreshed.append(key)
    return {"refreshed": refreshed, "failed": failed, "fresh": fresh}


def state_of(
    url: str,
    *,
    store: Mapping[str, dict] | None = None,
    now: datetime | None = None,
    stale_after: timedelta = DFLT_STALE_AFTER,
) -> dict | None:
    """``{"state", "title", "closed_at"}`` for an issue or pull request URL, or ``None`` when
    it is not one, the store has not seen it, or what it knows is older than ``stale_after``.

    >>> store = {'o/r': {'fetched_at': '2026-02-01T12:00:00+00:00',
    ...                  'items': {'3': {'state': 'closed', 'title': 'Fix it', 'closed_at': ''}}}}
    >>> at = datetime(2026, 2, 1, 13, tzinfo=timezone.utc)
    >>> state_of('https://github.com/o/r/issues/3', store=store, now=at)['state']
    'closed'
    >>> state_of('https://github.com/o/r/issues/3', store=store, now=at + timedelta(days=1)) is None
    True
    """
    kind, owner, repo, number = github_ref(url)
    if kind not in KINDS or not number:
        return None
    store = dflt_store() if store is None else store
    try:
        doc = store[f"{owner}/{repo}"]
    except KeyError:
        return None
    then = _when(doc.get("fetched_at"))
    now = datetime.now(timezone.utc) if now is None else now
    if then is None or now - then > stale_after:
        return None
    item = (doc.get("items") or {}).get(number)
    if not isinstance(item, Mapping) or item.get("state") not in (
        "open",
        "closed",
        "merged",
    ):
        return None
    return {
        "state": item["state"],
        "title": str(item.get("title") or ""),
        "closed_at": str(item.get("closed_at") or ""),
    }
