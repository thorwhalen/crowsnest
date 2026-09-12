"""References in a session's own words, turned into links you can click.

Sessions write references down constantly -- ``#17``, ``i2mint/mergeset#12``, a commit
sha, a CI run, an artifact URL -- and a roster that prints them as text makes the reader
reconstruct a URL by hand for every one. The user's own convention says the opposite:
*a reference is a full clickable link every time it appears, including the second time
and inside a table.* This module is that convention, automated.

**The non-obvious one is the bare ``#N``.** A session working in ``i2mint/mergeset`` that
writes ``#17`` means that repository's issue 17, and nothing in the text says so -- but
crowsnest already knows the session's working directory, and :func:`crowsnest.tools.repo_url`
already turns that into a remote. So the cheapest, most common reference a session writes
is resolvable exactly, and only here: a link resolver that did not know where the text was
written could never do it.

``resolvers=`` is the seam. A resolver is a callable ``(text, context) -> Iterable[Link]``
-- it owns its own pattern, because what a reference *looks like* and what it *resolves
to* are the same question, and splitting them into "find a token" and "map a token" makes
the markdown-link case (which is not token-shaped) impossible to express. They run in
order and the first link found for a given URL wins, so a better resolver put first
overrides a worse one. :data:`DFLT_RESOLVERS` is what a caller gets by leaving it out, in
the order they are worth:

===========================  ============================================================
resolver                     what it reads
===========================  ============================================================
:func:`from_markdown_links`  ``[label](url)`` a session already wrote out in full. The
                             highest-quality source there is, and it costs one parse.
:func:`from_urls`            a bare URL, typed by where it points (issue, pull request,
                             discussion, commit, CI run, artifact, session, Slack).
:func:`from_repo_refs`       ``owner/repo#N``, which names its own repository.
:func:`from_issue_refs`      a bare ``#N``, against the repository the session is working
                             in. The one that needs crowsnest to resolve at all.
:func:`from_commits`         a bare commit sha, against that same repository.
===========================  ============================================================

The ``context`` is a plain mapping, not an object, so it crosses every surface the way
everything else in crowsnest does: ``{"repo_url": "https://github.com/owner/repo"}`` is
the whole of it today.

Nothing here fetches anything. A link is *constructed* from what the text says and what
the session's directory implies; whether the issue exists is GitHub's business, and a
resolver that checked would turn a report into a few hundred network calls.

>>> found = resolve('fixed in #17', context={'repo_url': 'https://github.com/o/r'})
>>> found[0]['type'], found[0]['url'], found[0]['text']
('issue', 'https://github.com/o/r/issues/17', 'r#17')
>>> resolve('fixed in #17')                       # no repository, so no link
[]
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass

__all__ = [
    "DFLT_RESOLVERS",
    "MAX_LINKS",
    "Link",
    "dflt_resolvers",
    "from_commits",
    "from_issue_refs",
    "from_markdown_links",
    "from_repo_refs",
    "from_urls",
    "github_ref",
    "identity",
    "label_for",
    "resolve",
]

#: How many links one piece of text yields. A session re-records the same reference on
#: nearly every turn, so the cap is reached by breadth rather than by repetition -- the
#: de-duplication below happens first.
MAX_LINKS = 12

#: The schemes a link may use. Anything else is not a link for our purposes, and the
#: page's own sanitiser refuses it a second time on the way out.
_SCHEMES = ("https://", "http://")


@dataclass(frozen=True)
class Link:
    """One reference, resolved: what kind it is, where it goes, what to call it.

    Shaped like :class:`openloops.transcripts.Locator` on purpose -- ``type``, ``url``,
    ``text`` -- because the report already renders those, and a second shape for the same
    idea would mean a second renderer.

    >>> Link('issue', 'https://github.com/o/r/issues/1', 'r#1').as_dict()['type']
    'issue'
    """

    type: str
    url: str
    text: str = ""
    at: str = ""

    def as_dict(self) -> dict[str, str]:
        """JSON-ready form."""
        return asdict(self)


# --------------------------------------------------------------------------------------
# Reading a GitHub URL, which several resolvers need


_GITHUB = re.compile(
    r"^https?://github\.com/([\w.-]+)/([\w.-]+)"
    r"(?:/(issues|pull|discussions|commit|actions/runs)/([\w.]+))?"
)

#: What GitHub calls a thing in its URL, and what crowsnest calls it.
_GITHUB_KINDS = {
    "issues": "issue",
    "pull": "pr",
    "discussions": "discussion",
    "commit": "commit",
    "actions/runs": "run",
}


def github_ref(url: str) -> tuple[str, str, str, str]:
    """A GitHub URL as ``(kind, owner, repo, number)``; empty strings when it is not one.

    >>> github_ref('https://github.com/i2mint/mergeset/pull/27')
    ('pr', 'i2mint', 'mergeset', '27')
    >>> github_ref('https://github.com/o/r')
    ('repo', 'o', 'r', '')
    >>> github_ref('https://example.org/x')
    ('', '', '', '')
    """
    m = _GITHUB.match(str(url or "").rstrip("/"))
    if not m:
        return ("", "", "", "")
    owner, repo, path, number = m.group(1), m.group(2), m.group(3), m.group(4)
    if not path:
        return ("repo", owner, repo, "")
    return (_GITHUB_KINDS.get(path, path), owner, repo, number or "")


def _label(url: str) -> str:
    """What to call a URL when the text around it gave it no name.

    ``repo#27`` for anything numbered, a short sha for a commit, the host otherwise --
    the spellings a person already reads in a terminal.

    >>> _label('https://github.com/o/r/issues/3')
    'r#3'
    >>> _label('https://github.com/o/r/commit/abc1234def5678')
    'r@abc1234'
    >>> _label('https://claude.ai/code/artifact/x')
    'artifact'
    """
    kind, _, repo, number = github_ref(url)
    if kind == "commit" and number:
        return f"{repo}@{number[:7]}"
    if kind == "run" and number:
        return f"{repo} run {number}"
    if number:
        return f"{repo}#{number}"
    if kind == "repo":
        return repo
    other = _kind_of(url)
    if other != "link":
        return other
    return _KNOWN_HOSTS.get(_host(url), _host(url))


def _host(url: str) -> str:
    rest = str(url or "").partition("://")[2]
    return rest.partition("/")[0].removeprefix("www.")


#: Hosts worth naming by what they are rather than by their domain.
_KNOWN_HOSTS = {
    "claude.ai": "claude",
    "github.com": "github",
    "pypi.org": "pypi",
}


def _kind_of(url: str) -> str:
    """What a bare URL points at, as one word.

    >>> _kind_of('https://github.com/o/r/pull/1'), _kind_of('https://x.slack.com/archives/C1/p2')
    ('pr', 'slack')
    >>> _kind_of('https://claude.ai/code/artifact/abc'), _kind_of('https://example.org')
    ('artifact', 'link')
    """
    kind = github_ref(url)[0]
    if kind:
        return kind
    host, path = _host(url), str(url or "").partition("://")[2]
    if host.endswith("slack.com"):
        return "slack"
    if host == "claude.ai":
        if "/artifact" in path:
            return "artifact"
        return "session" if "/code/" in path else "claude"
    return "link"


# --------------------------------------------------------------------------------------
# The resolvers


_MARKDOWN_LINK = re.compile(r"\[([^\]\n]{1,120})\]\((https?://[^\s)]+)\)")


def from_markdown_links(text: str, context: Mapping) -> list[Link]:
    """``[label](url)`` a session already wrote out in full, keeping the label it chose.

    The best source available and the cheapest: a session that wrote a markdown link had
    the whole reference in hand and named it for a reader. Nothing is inferred.

    >>> from_markdown_links('see [PR 27](https://github.com/o/r/pull/27)', {})[0].text
    'PR 27'
    """
    return [
        Link(_kind_of(m.group(2)), m.group(2), m.group(1).strip())
        for m in _MARKDOWN_LINK.finditer(text or "")
    ]


_BARE_URL = re.compile(r"(?<![\(\]])\bhttps?://[^\s<>\"'\)\]]+")


def from_urls(text: str, context: Mapping) -> list[Link]:
    """A bare URL, typed by where it points and labelled the way a person would say it.

    >>> [(l.type, l.text) for l in from_urls('see https://github.com/o/r/issues/3', {})]
    [('issue', 'r#3')]
    """
    found = []
    for m in _BARE_URL.finditer(text or ""):
        url = m.group(0).rstrip(".,;:")
        found.append(Link(_kind_of(url), url, _label(url)))
    return found


_REPO_REF = re.compile(r"(?<![\w/#])([\w.-]+)/([\w.-]+)#(\d+)\b")


def from_repo_refs(text: str, context: Mapping) -> list[Link]:
    """``owner/repo#N``, which names its own repository and needs no context.

    The issue-or-pull-request ambiguity is left as ``issue``: GitHub redirects an issue
    URL to the pull request when that is what the number is, so the link works either
    way, and guessing would be a guess.

    >>> from_repo_refs('see i2mint/mergeset#12', {})[0].url
    'https://github.com/i2mint/mergeset/issues/12'
    """
    return [
        Link(
            "issue",
            f"https://github.com/{m.group(1)}/{m.group(2)}/issues/{m.group(3)}",
            f"{m.group(2)}#{m.group(3)}",
        )
        for m in _REPO_REF.finditer(text or "")
    ]


_ISSUE_REF = re.compile(r"(?<![\w/&#])#(\d{1,6})\b")


def from_issue_refs(text: str, context: Mapping) -> list[Link]:
    """A bare ``#N``, resolved against the repository the session is working in.

    This is the one that needs crowsnest. ``#17`` is the commonest reference a session
    writes and the least resolvable on its own; the session's working directory says which
    repository it means, and the roster already knows the directory.

    Nothing is produced without a ``repo_url`` in the context -- a wrong repository is
    worse than no link, because a link that goes somewhere plausible and wrong is one
    nobody checks.

    >>> from_issue_refs('closes #17', {'repo_url': 'https://github.com/o/r'})[0].url
    'https://github.com/o/r/issues/17'
    >>> from_issue_refs('closes #17', {})
    []
    """
    repo = str(context.get("repo_url") or "").rstrip("/")
    if not repo.startswith(_SCHEMES) or github_ref(repo)[0] != "repo":
        return []
    name = repo.rpartition("/")[2]
    return [
        Link("issue", f"{repo}/issues/{m.group(1)}", f"{name}#{m.group(1)}")
        for m in _ISSUE_REF.finditer(text or "")
    ]


_COMMIT = re.compile(r"(?<![\w/])([0-9a-f]{7,40})(?![\w])")


def from_commits(text: str, context: Mapping) -> list[Link]:
    """A bare commit sha, against the repository the session is working in.

    Held to a hexadecimal run of at least seven characters that is not part of a longer
    word, which is what git itself considers an abbreviated sha. A word that happens to be
    seven hex letters (``decade``, ``defaced``) is the false positive this accepts; it
    costs a link nobody clicks, where the alternative -- not linking shas at all -- costs
    the one reference a person most often wants to look up.

    >>> from_commits('fixed in 7d30838', {'repo_url': 'https://github.com/o/r'})[0].text
    'r@7d30838'
    """
    repo = str(context.get("repo_url") or "").rstrip("/")
    if not repo.startswith(_SCHEMES) or github_ref(repo)[0] != "repo":
        return []
    name = repo.rpartition("/")[2]
    return [
        Link("commit", f"{repo}/commit/{m.group(1)}", f"{name}@{m.group(1)[:7]}")
        for m in _COMMIT.finditer(text or "")
        if not m.group(1).isdigit()  # a long number is a number, not a sha
    ]


#: The resolvers :func:`resolve` uses when the caller names none, best first. Order is
#: precedence: the first resolver to claim a URL is the one whose label it keeps, which is
#: why the markdown one -- the only source where a human named the link -- comes first.
DFLT_RESOLVERS: tuple[Callable[[str, Mapping], Iterable[Link]], ...] = (
    from_markdown_links,
    from_urls,
    from_repo_refs,
    from_issue_refs,
    from_commits,
)


def dflt_resolvers() -> tuple[Callable[[str, Mapping], Iterable[Link]], ...]:
    """The default resolver order, as a function for callers that prefer one."""
    return DFLT_RESOLVERS


# --------------------------------------------------------------------------------------
# The one entry point


def resolve(
    text: str,
    *,
    context: Mapping | None = None,
    resolvers: Sequence[Callable[[str, Mapping], Iterable[Link]]] | None = None,
    limit: int = MAX_LINKS,
) -> list[dict]:
    """Every reference in ``text``, as JSON-able links, best first and de-duplicated.

    ``context`` is what the text cannot say for itself -- today just ``repo_url``, the
    repository the session writing it works in, which is what makes a bare ``#17``
    resolvable. ``resolvers`` is the seam (see the module docstring); they run in order
    and the first to claim a URL keeps its label, so a resolver placed first overrides
    those after it.

    The same reference appears many times in a session's text, so a URL is kept once, at
    the position it was first seen. Results come in **resolver order, not text order** --
    the markdown links a session wrote out in full first, the shas it happened to mention
    last -- because a page shows the first few and those should be the best few.
    ``limit`` bounds the result because this feeds a page meant to be read.

    >>> [l['text'] for l in resolve('see #1 and o/r#2', context={'repo_url': 'https://github.com/o/r'})]
    ['r#2', 'r#1']
    """
    context = {} if context is None else context
    found: dict[str, Link] = {}
    for resolver in DFLT_RESOLVERS if resolvers is None else resolvers:
        for link in _whatever_it_found(resolver, text, context):
            if link.url:
                found.setdefault(identity(link.url), link)
    return [link.as_dict() for link in list(found.values())[:limit]]


def identity(url: str) -> str:
    """What two links have in common when they are the same reference.

    A bare ``#45`` resolves to ``.../issues/45`` and a session that wrote the link out in
    full may have written ``.../pull/45`` -- **the same thing**, because GitHub redirects
    an issue URL to the pull request when that is what the number is. Showing both is the
    noise this feature exists to remove, so they collapse to one identity and the better
    label wins.

    A discussion does *not* collapse into them: ``discussions/45`` is a different object
    that happens to share a number.

    >>> identity('https://github.com/o/r/pull/45') == identity('https://github.com/o/r/issues/45')
    True
    >>> identity('https://github.com/o/r/discussions/45') == identity('https://github.com/o/r/issues/45')
    False
    """
    kind, owner, repo, number = github_ref(url)
    if kind in ("issue", "pr") and number:
        return f"github:{owner}/{repo}#{number}"
    return url


def label_for(url: str, text: str = "") -> str:
    """``text`` when it says something, else a name derived from the URL.

    The report calls this for references that reached it without a label -- openloops'
    own locators carry a URL and nothing else -- so that nothing renders as a bare,
    unclickable-looking blank.

    >>> label_for('https://github.com/o/r/pull/27')
    'r#27'
    >>> label_for('https://github.com/o/r/pull/27', 'the release PR')
    'the release PR'
    """
    text = " ".join(str(text or "").split())
    return text or _label(url)


def _whatever_it_found(
    resolver: Callable[[str, Mapping], Iterable[Link]], text: str, context: Mapping
) -> list[Link]:
    """One resolver's links, or none: a resolver that raises may not lose the others.

    Swallowed rather than raised because this runs once per session per render of a page
    whose job is to be readable; a custom resolver with a bad pattern should cost its own
    links and nothing else.
    """
    try:
        return list(resolver(text, context))
    except Exception:  # noqa: BLE001 -- any resolver, any failure; the others still count
        return []
