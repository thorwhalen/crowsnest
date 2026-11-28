"""Deliver the report page to a place its owner can open from anywhere -- by their route, not ours.

crowsnest renders the page; where it goes differs from one person to the next: a synced
folder, a server behind a login, a bucket. So delivering it takes a *destination* and a
*publisher*, and the destination lives in the person's config file, never in this code.

.. code-block:: toml

    # ~/.config/crowsnest/config.toml
    [publish]
    to = "~/Sync/crowsnest/index.html"          # a local path: written atomically

    # or: a host:path, sent with rsync over ssh, never prompting
    # to = "me@myserver:/srv/crowsnest/index.html"

    # or: any command, run without a shell; {page} is the rendered file
    # command = ["aws", "s3", "cp", "{page}", "s3://my-bucket/crowsnest.html"]

Run ``crowsnest publish`` from cron, launchd or a systemd timer and the page stays as
fresh as that schedule, with no session awake to tick it. **The page names your sessions
and quotes what they said** (sanitised as every page is), so publish it only where you
alone can read it.

A publisher is a callable ``(page, to) -> str``: it delivers the file ``page`` to ``to``
and says in one line where it went. :func:`dflt_publisher` picks one by the shape of
``to``; ``publisher=`` on :func:`crowsnest.tools.publish` replaces it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: The file a publish run leaves beside the page it kept: when it started and finished,
#: and the moment its page shows. It is how anything else can tell that the page a
#: person is looking at is old (:func:`state`), which the publisher itself cannot say
#: while it is the thing that is late.
STATUS_NAME = "status.json"

#: How old the published page may be before it counts as stale. The page is meant to be
#: as fresh as its schedule (a minute); a quarter of an hour is no longer a slow run.
DFLT_PAGE_STALE_AFTER = timedelta(minutes=15)

#: ``(page, to) -> str``: deliver ``page`` to ``to``, say where it went.
Publisher = Callable[[Path, str], str]

#: The placeholder a ``command`` publisher replaces with the rendered page's path.
PAGE_PLACEHOLDER = "{page}"

#: The file name a destination that is a directory receives.
DFLT_PAGE_NAME = "index.html"

#: Seconds rsync may stall, and ssh may take to connect, before a run gives up. A
#: scheduled publish that hangs would pile up behind itself.
DFLT_TIMEOUT = 20
DFLT_CONNECT_TIMEOUT = 10

#: How long an idle shared ssh connection stays open, in seconds. A scheduler that runs
#: once a minute then opens one connection per host per minute, not one per file: many
#: connections a minute is what a server's ssh throttling drops (`unexpected end of file`,
#: exit 255, about one publish in twenty before this).
DFLT_CONTROL_PERSIST = 120

#: Exits that mean the connection dropped rather than that the command was wrong: ssh's
#: 255, and rsync's socket (10), stream (12) and timeout (30, 35) errors. Such a run is
#: tried once more after :data:`RETRY_PAUSE` seconds.
TRANSIENT_EXITS = frozenset({10, 12, 30, 35, 255})
RETRIES = 1
RETRY_PAUSE = 3.0

# `host:path` or `user@host:path`, the way rsync and scp read one. A single letter before
# the colon is a Windows drive, and a slash before it makes a local path with a colon in it.
_REMOTE = re.compile(r"^(?:[^@/:\s]+@)?[^@/:\s]{2,}:")


def is_remote(to: str) -> bool:
    """Whether ``to`` names a file on another machine (``[user@]host:path``).

    >>> is_remote("me@box:/srv/page.html"), is_remote("box:page.html")
    (True, True)
    >>> is_remote("~/Sync/page.html"), is_remote("C:/page.html"), is_remote("./a:b")
    (False, False, False)
    """
    return bool(_REMOTE.match(to))


def to_path(page: Path, to: str) -> str:
    """Copy ``page`` to the local path ``to``, atomically: a reader never sees half a page.

    A ``to`` that is a directory, or ends with a slash, gets :data:`DFLT_PAGE_NAME` in it.
    """
    dest = Path(to).expanduser()
    if to.endswith(("/", os.sep)) or dest.is_dir():
        dest = dest / DFLT_PAGE_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(Path(page).read_bytes())
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return str(dest)


def ssh_command(
    *,
    connect_timeout: int = DFLT_CONNECT_TIMEOUT,
    control_dir: str | Path | None = None,
    control_persist: int = DFLT_CONTROL_PERSIST,
) -> str:
    """The ssh rsync runs (its ``-e``): never prompting, bounded, and sharing a connection.

    ``BatchMode`` makes ssh fail rather than prompt, which is what a job with no terminal
    needs: a prompt nobody can answer is a run that never ends. ``ControlMaster`` keeps one
    connection per host open for ``control_persist`` seconds under ``control_dir``
    (default ``<data dir>/ssh``), so a publish and a courier tick share it. Not on Windows,
    whose ssh has no control sockets, nor under a directory whose path holds a space,
    which rsync's ``-e`` would split.

    >>> ssh_command(control_dir='/tmp/cn-ssh').split(' -o ')[1:3]
    ['BatchMode=yes', 'ConnectTimeout=10']
    """
    ssh = f"ssh -o BatchMode=yes -o ConnectTimeout={connect_timeout}"
    if control_dir is None:
        from crowsnest.paths import data_dir

        control_dir = data_dir() / "ssh"
    control = Path(control_dir).expanduser()
    if os.name == "nt" or " " in str(control):
        return ssh
    try:
        control.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return ssh
    return (
        f"{ssh} -o ControlMaster=auto -o ControlPath={control}/%C"
        f" -o ControlPersist={control_persist}"
    )


def rsync_argv(
    page: Path,
    to: str,
    *,
    timeout: int = DFLT_TIMEOUT,
    connect_timeout: int = DFLT_CONNECT_TIMEOUT,
) -> list[str]:
    """The rsync command :func:`to_rsync` runs: quiet, bounded, and never asking for input."""
    ssh = ssh_command(connect_timeout=connect_timeout)
    return ["rsync", "-q", f"--timeout={timeout}", "-e", ssh, str(page), to]


def to_rsync(page: Path, to: str) -> str:
    """Send ``page`` to the remote ``[user@]host:path`` ``to`` with rsync over ssh."""
    if not shutil.which("rsync"):
        raise ValueError(
            f"publishing to {to!r} needs rsync, which is not on PATH. Install it, or set "
            f"[publish] command in the config file to send the page another way."
        )
    _run(rsync_argv(page, to), what=f"rsync to {to}")
    return to


def command_publisher(argv: Sequence[str]) -> Publisher:
    """A publisher running ``argv``, with :data:`PAGE_PLACEHOLDER` replaced by the page.

    Run without a shell, so nothing in the page's path is interpreted. ``to`` is ignored:
    the command says where the page goes.
    """
    argv = list(argv)
    if not argv or not any(PAGE_PLACEHOLDER in a for a in argv):
        raise ValueError(
            f"a publish command must name the page as {PAGE_PLACEHOLDER} in one of its "
            f"arguments, or it would send something else: {argv!r}"
        )

    def publish(page: Path, to: str) -> str:
        _run([a.replace(PAGE_PLACEHOLDER, str(page)) for a in argv], what=argv[0])
        return " ".join(argv)

    return publish


def dflt_publisher(to: str) -> Publisher:
    """rsync over ssh for a ``[user@]host:path``, an atomic local write for anything else."""
    return to_rsync if is_remote(to) else to_path


def attempt(
    argv: list[str],
    *,
    retries: int = RETRIES,
    pause: float | None = None,
    sleep: Callable[[float], None] | None = None,
) -> subprocess.CompletedProcess:
    """Run ``argv``, again after ``pause`` seconds (:data:`RETRY_PAUSE`) while it exits with
    a dropped connection (:data:`TRANSIENT_EXITS`), at most ``retries`` more times; the
    last run is returned."""
    pause = RETRY_PAUSE if pause is None else pause
    sleep = time.sleep if sleep is None else sleep
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    for _ in range(retries):
        if done.returncode not in TRANSIENT_EXITS:
            break
        sleep(pause)
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
    return done


def _run(argv: list[str], *, what: str) -> None:
    """Run ``argv``; a failure is a ``ValueError`` naming the command and its last words."""
    done = attempt(argv)
    if done.returncode:
        said = (done.stderr or done.stdout).strip().splitlines()
        tail = said[-1] if said else "no output"
        raise ValueError(f"publishing failed: {what} exited {done.returncode}: {tail}")


# ---------------------------------------------------------------------------------------
# The record of the last run, and whether the page it left is stale
# ---------------------------------------------------------------------------------------


def _moment(text) -> datetime | None:
    """An ISO time as an aware datetime, or ``None``."""
    try:
        found = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def span(seconds: float) -> str:
    """A length of time as a person says it: ``42 s``, ``7 min``, ``3 h 18 min``.

    >>> span(42), span(420), span(11880), span(7200)
    ('42 s', '7 min', '3 h 18 min', '2 h')
    """
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} s"
    hours, minutes = divmod(round(seconds / 60), 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def record_run(
    folder: str | Path,
    *,
    made_at: str,
    started_at: datetime,
    finished_at: datetime | None = None,
    to: str = "",
    size: int = 0,
) -> dict:
    """Write what one publish run did into ``folder`` (:data:`STATUS_NAME`), and return it.

    ``made_at`` is the moment the page shows (a slow run publishes an old moment);
    ``seconds`` is how long the run took. Written whole, so a reader never sees half.
    """
    finished_at = finished_at or datetime.now(timezone.utc)
    run = {
        "made_at": made_at,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "seconds": round((finished_at - started_at).total_seconds(), 1),
        "to": to,
        "bytes": size,
    }
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".status-")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(run, stream)
    os.replace(temp, folder / STATUS_NAME)
    return run


def state(
    folder: str | Path,
    *,
    now: datetime | None = None,
    stale_after: timedelta = DFLT_PAGE_STALE_AFTER,
) -> dict:
    """How old the published page is: ``{"known", "made_at", "seconds", "age", "stale"}``.

    ``age`` is the seconds between ``now`` and the moment the last finished run's page
    shows. The page is ``stale`` when nothing has finished for ``stale_after``, or when
    the last run itself took that long: runs that each take forty minutes leave a page
    that is never current, and a test on the page's age alone would call it stale and
    fresh in turn at every run. With no record yet (nothing has published from this
    folder) ``known`` is false and nothing is called stale: an unknown is never reported
    as a fault.

    >>> import tempfile
    >>> where = tempfile.mkdtemp()
    >>> state(where)["known"]
    False
    >>> at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    >>> _ = record_run(where, made_at="2026-01-01T08:42:00+00:00",
    ...                started_at=at - timedelta(hours=3, minutes=18), finished_at=at)
    >>> found = state(where, now=at + timedelta(minutes=5))
    >>> found["stale"], span(found["age"]), span(found["seconds"])
    (True, '3 h 23 min', '3 h 18 min')
    >>> _ = record_run(where, made_at="2026-01-01T12:00:00+00:00",
    ...                started_at=at, finished_at=at + timedelta(minutes=9))
    >>> [state(where, now=at + timedelta(minutes=m))["stale"] for m in (10, 23, 25)]
    [False, False, True]
    """
    try:
        run = json.loads((Path(folder) / STATUS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"known": False, "stale": False}
    made = _moment(run.get("made_at")) if isinstance(run, dict) else None
    if made is None:
        return {"known": False, "stale": False}
    now = now or datetime.now(timezone.utc)
    age = max(0.0, (now - made).total_seconds())
    try:
        seconds = max(0.0, float(run.get("seconds") or 0))
    except (TypeError, ValueError):
        seconds = 0.0
    finished = _moment(run.get("finished_at")) or made
    limit = stale_after.total_seconds()
    return {
        "known": True,
        "made_at": str(run["made_at"]),
        "finished_at": str(run.get("finished_at") or ""),
        "seconds": seconds,
        "age": age,
        "stale": (now - finished).total_seconds() > limit or seconds > limit,
    }


#: Where :func:`staleness_event` remembers what it last said, beside the run record.
TOLD_NAME = "status-told.json"


def staleness_event(
    folder: str | Path,
    *,
    now: datetime | None = None,
    stale_after: timedelta = DFLT_PAGE_STALE_AFTER,
) -> dict | None:
    """The event-log line to write now about the page's age, or ``None``.

    One ``page_stale`` line when the page first counts as stale, and one ``page_fresh``
    line when a run has brought it back: a change is said once, never on every tick.
    Something that runs on its own schedule calls this (the courier's tick does): the
    publisher cannot, because a publisher that is late is not there to say so.

    This only reads. Once the line is in the log, the caller says so with :func:`told`;
    a line that could not be written is then offered again at the next tick.

    >>> import tempfile
    >>> where = tempfile.mkdtemp()
    >>> at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    >>> _ = record_run(where, made_at="2026-01-01T11:59:00+00:00",
    ...                started_at=at - timedelta(minutes=1), finished_at=at)
    >>> staleness_event(where, now=at) is None
    True
    >>> late = staleness_event(where, now=at + timedelta(hours=2))
    >>> late["event"], late["detail"]
    ('page_stale', 'the published page shows 11:59 UTC, 2 h 1 min ago; its last run took 60 s')
    >>> staleness_event(where, now=at + timedelta(hours=3))["event"]  # not told yet
    'page_stale'
    >>> told(where, late)
    >>> staleness_event(where, now=at + timedelta(hours=3)) is None
    True
    >>> _ = record_run(where, made_at="2026-01-01T15:00:00+00:00",
    ...                started_at=at + timedelta(hours=3), finished_at=at + timedelta(hours=3))
    >>> staleness_event(where, now=at + timedelta(hours=3, minutes=1))["event"]
    'page_fresh'
    """
    now = now or datetime.now(timezone.utc)
    found = state(folder, now=now, stale_after=stale_after)
    if not found["known"]:
        return None
    try:
        was = json.loads((Path(folder) / TOLD_NAME).read_text(encoding="utf-8"))
        was = isinstance(was, dict) and was.get("stale") is True
    except (OSError, ValueError):
        was = False
    if found["stale"] == was:
        return None
    shown = _moment(found["made_at"]).astimezone(timezone.utc).strftime("%H:%M UTC")
    if found["stale"]:
        detail = (
            f"the published page shows {shown}, {span(found['age'])} ago; "
            f"its last run took {span(found['seconds'])}"
        )
    else:
        detail = f"the published page is current again (shows {shown})"
    return {
        "event": "page_stale" if found["stale"] else "page_fresh",
        "at": now.isoformat(timespec="seconds"),
        "name": "page",
        "project": "",
        "detail": detail,
    }


def told(folder: str | Path, event: Mapping) -> None:
    """Remember that ``event`` (a line :func:`staleness_event` gave) is in the log, so the
    same change is not said again."""
    (Path(folder) / TOLD_NAME).write_text(
        json.dumps({"stale": event.get("event") == "page_stale"}), encoding="utf-8"
    )
