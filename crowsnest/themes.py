"""Which theme each session belongs to: the person's ``[themes]`` table first, then what
the row itself says (the action-first pass, C1).

A theme is a line of work that spans repositories ("the video product", "the website").
Only the person knows those lines, so they are named in the config file, and everything
else is inferred, in order, first hit wins, and every row lands somewhere:

1. **override**: the ``[themes]`` table, whose values match a row's repository as
   ``owner/name``, then a bare repository name, then a glob over its directory, then
   ``org:<owner>``, in that order across the whole table;
2. the row's repository **owner**;
3. the **parent**'s theme, for a session with no repository that another one started;
4. the repository most of its **references** point at, themed by rules 1 and 2;
5. ``unthemed``, a theme like any other, never dropped.

.. code-block:: toml

    [themes]
    video = ["acme/player", "encoder", "org:acme-media"]
    website = ["web/*", "site-builder"]

A directory glob holding no ``/`` or ``~`` at its start matches anywhere in the path:
``web/*`` matches ``/home/me/code/web/landing``.

Nothing here reads a file or a transcript: :func:`infer` takes rows and the table, and
:func:`crowsnest.config.theme_table` is what reads the config.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from crowsnest.links import github_ref

__all__ = ["NOT_OWNERS", "RULES", "UNTHEMED", "Theme", "Themes", "infer", "parents_of"]

#: The theme of a row nothing placed.
UNTHEMED = "unthemed"

#: Each rule's number and what it says, for a theme's ``title``.
RULES = {
    1: "named in the [themes] table",
    2: "its repository's owner",
    3: "the theme of the session that started it",
    4: "the repository most of its references point at",
    5: "nothing placed it",
}

#: How many parents rule 3 climbs before giving up (a lineage has no cycles, but a
#: hand-built one might).
MAX_CLIMB = 8

#: GitHub paths that sit where an owner would and are not one (``github.com/settings/…``).
NOT_OWNERS = frozenset(
    {
        "settings",
        "orgs",
        "apps",
        "marketplace",
        "notifications",
        "sponsors",
        "features",
        "topics",
        "search",
        "login",
        "new",
        "organizations",
        "account",
        "explore",
    }
)

#: The kinds a table value can be, in the order they are tried.
_KINDS = ("repo", "name", "path", "org")


@dataclass(frozen=True)
class Theme:
    """A row's theme and which rule placed it."""

    name: str
    rule: int

    @property
    def how(self) -> str:
        """``override`` when the person named it, ``inferred`` otherwise."""
        return "override" if self.rule == 1 else "inferred"


def _kind(value: str) -> tuple[str, str]:
    """A table value as ``(kind, value)``.

    >>> _kind('org:Acme'), _kind('acme/player'), _kind('encoder'), _kind('web/*')
    (('org', 'acme'), ('repo', 'acme/player'), ('name', 'encoder'), ('path', 'web/*'))
    """
    text = value.strip()
    if text.lower().startswith("org:"):
        return "org", text[4:].strip().lower()
    if any(c in text for c in "*?[") or text.startswith(("/", "~")):
        return "path", text
    if "/" in text:
        return "repo", text.lower()
    return "name", text.lower()


def _path_matches(pattern: str, cwd: str) -> bool:
    if not cwd:
        return False
    if pattern.startswith(("/", "~")):
        full = str(Path(pattern).expanduser())
        return fnmatchcase(cwd, full) or fnmatchcase(cwd, full.rstrip("/") + "/*")
    return fnmatchcase(cwd, "*/" + pattern) or fnmatchcase(cwd, "*/" + pattern + "/*")


@dataclass(frozen=True)
class Themes:
    """The ``[themes]`` table, parsed: ``((theme, ((kind, value), ...)), ...)``."""

    table: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()

    @classmethod
    def of(cls, table: Mapping[str, Iterable[str]] | None) -> Themes:
        """From the config file's shape, ``{theme: [value, ...]}``."""
        return cls(
            tuple(
                (str(name), tuple(_kind(str(v)) for v in values))
                for name, values in (table or {}).items()
            )
        )

    def named(self, *, owner: str = "", repo: str = "", cwd: str = "") -> str | None:
        """The theme the table gives a repository or a directory, ``None`` when none."""
        found = {
            "repo": f"{owner}/{repo}".lower() if owner and repo else "",
            "name": repo.lower(),
            "org": owner.lower(),
        }
        for kind in _KINDS:
            for theme, values in self.table:
                for value_kind, value in values:
                    if value_kind != kind:
                        continue
                    if kind == "path":
                        if _path_matches(value, cwd):
                            return theme
                    elif found[kind] and found[kind] == value:
                        return theme
        return None


def _repo(row: Mapping[str, Any]) -> tuple[str, str]:
    _, owner, repo, _ = github_ref(str(row.get("repo_url") or ""))
    return owner, repo


def _ref_repos(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    found = []
    for link in row.get("links") or ():
        if isinstance(link, Mapping):
            _, owner, repo, _ = github_ref(str(link.get("url") or ""))
            if owner and repo and owner.lower() not in NOT_OWNERS:
                found.append((owner, repo))
    return found


def _key(row: Mapping[str, Any]) -> str:
    return str(row.get("session_id") or row.get("label") or "")


def parents_of(lineage: Mapping[str, Any] | None) -> dict[str, str]:
    """``{session id: its parent's session id}`` from :func:`crowsnest.lineage.graph`."""
    if not isinstance(lineage, Mapping):
        return {}
    nodes = [n for n in lineage.get("nodes") or () if isinstance(n, Mapping)]
    by_name = {n.get("name"): n for n in nodes}
    found = {}
    for node in nodes:
        parent = by_name.get(node.get("parent"))
        if parent and node.get("session_id") and parent.get("session_id"):
            found[str(node["session_id"])] = str(parent["session_id"])
    return found


def infer(
    rows: Sequence[Mapping[str, Any]],
    *,
    themes: Themes | None = None,
    parents: Mapping[str, str] | None = None,
) -> Callable[[Mapping[str, Any]], Theme]:
    """A function giving each row its :class:`Theme`, by the rules in the module docstring.

    ``parents`` maps a session id to its parent's (:func:`parents_of`); a parent that is not
    among ``rows`` is not climbed to.
    """
    themes = themes or Themes()
    parents = dict(parents or {})
    by_key = {_key(r): r for r in rows}

    def own(row: Mapping[str, Any]) -> Theme | None:
        owner, repo = _repo(row)
        named = themes.named(owner=owner, repo=repo, cwd=str(row.get("cwd") or ""))
        if named:
            return Theme(named, 1)
        if owner:
            return Theme(owner, 2)
        return None

    def theme_of(row: Mapping[str, Any]) -> Theme:
        found = own(row)
        if found:
            return found
        key = _key(row)
        for _ in range(MAX_CLIMB):
            key = parents.get(key, "")
            parent = by_key.get(key)
            if parent is None:
                break
            found = own(parent)
            if found:
                return Theme(found.name, 3)
        repos = Counter(_ref_repos(row)).most_common()
        if repos:
            (owner, repo), _ = repos[0]
            return Theme(themes.named(owner=owner, repo=repo) or owner, 4)
        return Theme(UNTHEMED, 5)

    return theme_of
