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

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

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


def rsync_argv(
    page: Path,
    to: str,
    *,
    timeout: int = DFLT_TIMEOUT,
    connect_timeout: int = DFLT_CONNECT_TIMEOUT,
) -> list[str]:
    """The rsync command :func:`to_rsync` runs: quiet, bounded, and never asking for input.

    ``BatchMode`` makes ssh fail rather than prompt, which is what a job with no terminal
    needs: a prompt nobody can answer is a run that never ends.
    """
    ssh = f"ssh -o BatchMode=yes -o ConnectTimeout={connect_timeout}"
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


def _run(argv: list[str], *, what: str) -> None:
    """Run ``argv``; a failure is a ``ValueError`` naming the command and its last words."""
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    if done.returncode:
        said = (done.stderr or done.stdout).strip().splitlines()
        tail = said[-1] if said else "no output"
        raise ValueError(f"publishing failed: {what} exited {done.returncode}: {tail}")
