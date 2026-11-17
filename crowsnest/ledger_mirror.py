"""Carry this machine's ledgers to the page that shows them, with no session remembering to.

A ledger is written where its session runs (:mod:`crowsnest.ledger`). Its reader is
elsewhere: a page on a server, read from a phone. Asking each session to publish its own
ledger fails the way any reminder fails (a brief's wording wins over a rule it does not
repeat), so the copy is mechanical: :func:`push` sends the whole ledger folder to a
*mirror* on every scheduled ``crowsnest publish``, newer copy wins, nothing is deleted.
Each machine pushes into its own mirror (``.../ledger-hosts/<machine>/``), so two machines
that happen to use one session name never overwrite each other.

.. code-block:: toml

    # ~/.config/crowsnest/config.toml
    [ledgers]
    mirror = "me@myserver:/srv/ledger-hosts/laptop"     # or a local directory
    url = "https://example.com/ledgers/laptop/{name}.md"  # one ledger's page; {name} is its stem
    page = "https://example.com/ledgers"                  # every ledger, newest first

Each push records how it went in ``<data dir>/ledger-push.json``. :func:`stale` reads that
record and the folder's times, and lists the ledgers changed since the last push that
worked, once they have had ``grace`` seconds to go: that is the check that would have said,
on the first day, that ledgers had stopped reaching their page.

The transport is a seam: ``copy=(src_dir, dst) -> None``. The default is rsync over ssh
(``-a --update``, never prompting, never deleting) for a ``[user@]host:path``, and a local
newer-wins copy for a directory.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shlex
import shutil
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from crowsnest.ledger import ledger_dir as _ledger_dir
from crowsnest.ledger import safe_name
from crowsnest.paths import data_dir

__all__ = [
    "DFLT_GRACE",
    "STAMP_NAME",
    "dflt_tree_copy",
    "link",
    "local_tree_copy",
    "push",
    "rsync_tree_copy",
    "stale",
]

#: ``(src_dir, dst) -> None``: make ``dst`` hold every file of ``src_dir``, newer wins.
TreeCopy = Callable[[str, str], None]

#: Where :func:`push` records its last run, under the data directory.
STAMP_NAME = "ledger-push.json"

#: Seconds a changed ledger is given to reach its mirror before :func:`stale` names it:
#: several scheduled runs, so one dropped connection is not an alarm.
DFLT_GRACE = 15 * 60

#: Seconds rsync may stall before a push gives up (a scheduled run must not pile up).
DFLT_TIMEOUT = 60

#: Placeholder in ``[ledgers] url`` for the ledger's file stem.
NAME_PLACEHOLDER = "{name}"


#: Names never carried: hidden files, caches, and a writer's temp file (``x.md.tmp``).
SKIPPED = (".*", "__pycache__", "*.tmp")

#: rsync's exit for "some files vanished before they could be transferred": a ledger
#: rewritten during the push. The next push carries it, so that is not a failure.
RSYNC_VANISHED = 24


def _skip(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in SKIPPED)


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat(timespec="seconds")


def _stamp_path(stamp_path: str | Path | None) -> Path:
    return Path(stamp_path).expanduser() if stamp_path else data_dir() / STAMP_NAME


def _read_stamp(stamp_path: str | Path | None) -> dict:
    try:
        return json.loads(_stamp_path(stamp_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_stamp(record: dict, stamp_path: str | Path | None) -> None:
    path = _stamp_path(stamp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(record, indent=2))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------------------
# Moving the folder


def local_tree_copy(src: str, dst: str) -> None:
    """Copy every file under ``src`` into ``dst``, each only when newer; never delete.

    Times are kept, so a copy is never newer than what it copied. Hidden files, caches,
    temp files and symlinks are skipped (a link could point outside the folder), and a file
    that vanishes mid-copy is left for the next run.

    >>> import tempfile, pathlib
    >>> a, b = pathlib.Path(tempfile.mkdtemp()), pathlib.Path(tempfile.mkdtemp()) / 'm'
    >>> _ = (a / 'x.md').write_text('x'); (a / 'sub').mkdir(); _ = (a / 'sub' / 'y.md').write_text('y')
    >>> local_tree_copy(str(a), str(b))
    >>> sorted(p.relative_to(b).as_posix() for p in b.rglob('*.md'))
    ['sub/y.md', 'x.md']
    """
    root, there = Path(src).expanduser(), Path(dst).expanduser()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _skip(d)]
        rel = Path(dirpath).relative_to(root)
        for name in filenames:
            if _skip(name):
                continue
            source, target = Path(dirpath) / name, there / rel / name
            try:
                if source.is_symlink():
                    continue
                if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(f".{name}.tmp")
                shutil.copy2(source, tmp)
                tmp.replace(target)
            except FileNotFoundError:
                continue


def rsync_tree_argv(src: str, dst: str, *, timeout: int = DFLT_TIMEOUT) -> list[str]:
    """``rsync -a --update`` of ``src/`` into the remote ``dst/``, which it creates first.

    Never ``--delete``: a ledger that left this machine stays on its page.

    >>> argv = rsync_tree_argv('/l/ledger', 'box:/srv/hosts/mac')
    >>> argv[-2:], '--delete' in argv, argv[-3]
    (['/l/ledger/', 'box:/srv/hosts/mac/'], False, '--rsync-path=mkdir -p /srv/hosts/mac/ && rsync')
    """
    from crowsnest.publish import ssh_command

    target = dst.rstrip("/") + "/"
    path = target.split(":", 1)[1] or "."
    return [
        "rsync",
        "-a",
        "-q",
        "--update",
        "--no-owner",
        "--no-group",
        *(f"--exclude={pat}" for pat in SKIPPED),
        f"--timeout={timeout}",
        "-e",
        ssh_command(),
        f"--rsync-path=mkdir -p {shlex.quote(path)} && rsync",
        str(src).rstrip("/") + "/",
        target,
    ]


def rsync_tree_copy(src: str, dst: str) -> None:
    """Push ``src`` to the remote ``dst`` with rsync over ssh; a failure raises ``ValueError``."""
    from crowsnest.publish import attempt

    if not shutil.which("rsync"):
        raise ValueError(
            "pushing ledgers to a host:path needs rsync, which is not on PATH"
        )
    done = attempt(rsync_tree_argv(src, dst))
    if done.returncode not in (0, RSYNC_VANISHED):
        said = (done.stderr or done.stdout).strip().splitlines()
        tail = said[-1] if said else "no output"
        raise ValueError(f"ledger push: rsync to {dst} exited {done.returncode}: {tail}")


def dflt_tree_copy(dst: str) -> TreeCopy:
    """rsync over ssh for a ``[user@]host:path``, a local newer-wins copy for a directory."""
    from crowsnest.publish import is_remote

    return rsync_tree_copy if is_remote(dst) else local_tree_copy


# --------------------------------------------------------------------------------------
# The three verbs


def push(
    mirror: str,
    *,
    ledger_dir: str | Path | None = None,
    copy: TreeCopy | None = None,
    stamp_path: str | Path | None = None,
    clock: Callable[[], float] = time.time,
) -> dict:
    """Copy the whole ledger folder to ``mirror`` and record how it went.

    Returns ``{"ok", "to", "files", "started", "last_ok", "error"}``. A failure is
    recorded and returned, not raised, so a scheduled run that also publishes a page
    still publishes it; :func:`stale` is what makes a failure that persists visible.
    """
    if not mirror:
        raise ValueError(
            "a ledger push needs a mirror: [ledgers] mirror in the config file"
        )
    src = _ledger_dir(ledger_dir)
    copy = copy or dflt_tree_copy(mirror)
    before = _read_stamp(stamp_path)
    started = clock()
    record = {
        "to": mirror,
        "started": _iso(started),
        "started_ts": started,
        "last_ok": before.get("last_ok", ""),
        "last_ok_ts": before.get("last_ok_ts", 0.0),
        "ok": False,
        "error": "",
        "files": 0,
    }
    if not src.is_dir():
        record.update(ok=True, last_ok=record["started"], last_ok_ts=started)
        _write_stamp(record, stamp_path)
        return record
    try:
        copy(str(src), mirror)
    except Exception as e:  # noqa: BLE001 -- recorded; stale() is the alarm
        record["error"] = str(e) or type(e).__name__
    else:
        record.update(ok=True, last_ok=record["started"], last_ok_ts=started)
        record["files"] = sum(1 for p in src.glob("*.md"))
    _write_stamp(record, stamp_path)
    return record


def stale(
    *,
    mirror: str | None = None,
    ledger_dir: str | Path | None = None,
    stamp_path: str | Path | None = None,
    grace: float = DFLT_GRACE,
    clock: Callable[[], float] = time.time,
) -> dict:
    """The ledgers changed since the last push that worked, older than ``grace`` seconds.

    Returns ``{"names", "last_ok", "error", "never"}``: ``names`` sorted newest first,
    ``never`` true when no push has ever worked here (every ledger past its grace counts).
    A stamp recorded for another ``mirror`` counts as none: a repointed mirror starts empty.
    """
    src = _ledger_dir(ledger_dir)
    stamp = _read_stamp(stamp_path)
    if mirror is not None and stamp.get("to") != mirror:
        stamp = {}
    last_ok = float(stamp.get("last_ok_ts") or 0.0)
    cutoff = clock() - grace
    found = []
    if src.is_dir():
        for path in src.glob("*.md"):
            mtime = path.stat().st_mtime
            if last_ok < mtime <= cutoff:
                found.append((mtime, path.stem))
    found.sort(reverse=True)
    return {
        "names": [name for _, name in found],
        "last_ok": stamp.get("last_ok", ""),
        "error": stamp.get("error", ""),
        "never": not last_ok,
    }


def link(name: str, url: str) -> str:
    """One ledger's page: ``url`` with ``{name}`` replaced by the ledger's file stem.

    >>> link('soma accomp', 'https://example.com/ledgers/mac/{name}.md')
    'https://example.com/ledgers/mac/soma-accomp.md'
    """
    if NAME_PLACEHOLDER not in url:
        raise ValueError(
            f"[ledgers] url must hold {NAME_PLACEHOLDER} where the ledger's name goes: {url!r}"
        )
    return url.replace(NAME_PLACEHOLDER, safe_name(name))
