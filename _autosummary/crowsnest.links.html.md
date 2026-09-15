# crowsnest.links

References in a session’s own words, turned into links you can click.

Sessions write references down constantly – `#17`, `i2mint/mergeset#12`, a commit
sha, a CI run, an artifact URL – and a roster that prints them as text makes the reader
reconstruct a URL by hand for every one. The user’s own convention says the opposite:
\*a reference is a full clickable link every time it appears, including the second time
and inside a table.\* This module is that convention, automated.

\*\*The non-obvious one is the bare `#N`.\*\* A session working in `i2mint/mergeset` that
writes `#17` means that repository’s issue 17, and nothing in the text says so – but
crowsnest already knows the session’s working directory, and [`crowsnest.tools.repo_url()`](crowsnest.tools.html.md#crowsnest.tools.repo_url)
already turns that into a remote. So the cheapest, most common reference a session writes
is resolvable exactly, and only here: a link resolver that did not know where the text was
written could never do it.

`resolvers=` is the seam. A resolver is a callable `(text, context) -> Iterable[Link]`
– it owns its own pattern, because what a reference *looks like* and what it \*resolves
to\* are the same question, and splitting them into “find a token” and “map a token” makes
the markdown-link case (which is not token-shaped) impossible to express. They run in
order and the first link found for a given URL wins, so a better resolver put first
overrides a worse one. [`DFLT_RESOLVERS`](#crowsnest.links.DFLT_RESOLVERS) is what a caller gets by leaving it out, in
the order they are worth:

| resolver                                                               | what it reads                                                                                                         |
|------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`from_markdown_links()`](#crowsnest.links.from_markdown_links) | `[label](url)` a session already wrote out in full. The<br/>highest-quality source there is, and it costs one parse.  |
| [`from_urls()`](#crowsnest.links.from_urls)           | a bare URL, typed by where it points (issue, pull request,<br/>discussion, commit, CI run, artifact, session, Slack). |
| [`from_repo_refs()`](#crowsnest.links.from_repo_refs)      | `owner/repo#N`, which names its own repository.                                                                       |
| [`from_issue_refs()`](#crowsnest.links.from_issue_refs)     | a bare `#N`, against the repository the session is working<br/>in. The one that needs crowsnest to resolve at all.    |
| [`from_commits()`](#crowsnest.links.from_commits)        | a bare commit sha, against that same repository.                                                                      |

The `context` is a plain mapping, not an object, so it crosses every surface the way
everything else in crowsnest does: `{"repo_url": "https://github.com/owner/repo"}` is
the whole of it today.

Nothing here fetches anything. A link is *constructed* from what the text says and what
the session’s directory implies; whether the issue exists is GitHub’s business, and a
resolver that checked would turn a report into a few hundred network calls.

```pycon
>>> found = resolve('fixed in #17', context={'repo_url': 'https://github.com/o/r'})
>>> found[0]['type'], found[0]['url'], found[0]['text']
('issue', 'https://github.com/o/r/issues/17', 'r#17')
>>> resolve('fixed in #17')                       # no repository, so no link
[]
```

### Module Attributes

| [`MAX_LINKS`](#crowsnest.links.MAX_LINKS)         | How many links one piece of text yields.                                                                              |
|--------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| [`SECRET_URL_SHAPES`](#crowsnest.links.SECRET_URL_SHAPES) | holding it is the whole of the permission, so printing it on a page is disclosing it.                                 |
| [`DFLT_RESOLVERS`](#crowsnest.links.DFLT_RESOLVERS)    | The resolvers [`resolve()`](#crowsnest.links.resolve) uses when the caller names none, best first. |

### Functions

| [`from_commits`](#crowsnest.links.from_commits)(text, context)                    | A bare commit sha, against the repository the session is working in.             |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`from_issue_refs`](#crowsnest.links.from_issue_refs)(text, context)                 | A bare `#N`, resolved against the repository the session is working in.          |
| [`from_markdown_links`](#crowsnest.links.from_markdown_links)(text, context)             | `[label](url)` a session already wrote out in full, keeping the label it chose.  |
| [`from_repo_refs`](#crowsnest.links.from_repo_refs)(text, context)                  | `owner/repo#N`, which names its own repository and needs no context.             |
| [`from_urls`](#crowsnest.links.from_urls)(text, context)                       | A bare URL, typed by where it points and labelled the way a person would say it. |
| [`github_ref`](#crowsnest.links.github_ref)(url)                                | A GitHub URL as `(kind, owner, repo, number)`; empty strings when it is not one. |
| [`identity`](#crowsnest.links.identity)(url)                                  | What two links have in common when they are the same reference.                  |
| [`kind_of`](#crowsnest.links.kind_of)(url)                                   | What a bare URL points at, as one word.                                          |
| [`label_for`](#crowsnest.links.label_for)(url[, text])                         | `text` when it says something, else a name derived from the URL.                 |
| [`looks_like_a_secret`](#crowsnest.links.looks_like_a_secret)(url)                       | Is this a URL that *is* a credential, rather than one that merely needs one?     |
| [`resolve`](#crowsnest.links.resolve)(text, \*[, context, resolvers, limit]) | Every reference in `text`, as JSON-able links, best first and de-duplicated.     |
| [`without_written_out_links`](#crowsnest.links.without_written_out_links)(text)                | `text` with every markdown link and bare URL blanked, lengths preserved.         |

### Classes

| [`Link`](#crowsnest.links.Link)(type, url[, text])   | One reference, resolved: what kind it is, where it goes, what to call it.   |
|----------------------------------------------------------------------------|-----------------------------------------------------------------------------|

### crowsnest.links.DFLT_RESOLVERS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Callable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Mapping](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)], [Iterable](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterable)[[Link](#crowsnest.links.Link)]], ...]* *= (<function from_markdown_links>, <function from_urls>, <function from_repo_refs>, <function from_issue_refs>, <function from_commits>)*

The resolvers [`resolve()`](#crowsnest.links.resolve) uses when the caller names none, best first. Order is
precedence: the first resolver to claim a URL is the one whose label it keeps, which is
why the markdown one – the only source where a human named the link – comes first.

### *class* crowsnest.links.Link(type, url, text='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One reference, resolved: what kind it is, where it goes, what to call it.

Shaped like `openloops.transcripts.Locator` on purpose – `type`, `url`,
`text` – because the report already renders those, and a second shape for the same
idea would mean a second renderer.

```pycon
>>> Link('issue', 'https://github.com/o/r/issues/1', 'r#1').as_dict()['type']
'issue'
```

#### as_dict()

JSON-ready form.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### crowsnest.links.MAX_LINKS *= 12*

How many links one piece of text yields. A session re-records the same reference on
nearly every turn, so the cap is reached by breadth rather than by repetition – the
de-duplication below happens first.

### crowsnest.links.SECRET_URL_SHAPES *= (re.compile('^https?://hooks\\\\.slack\\\\.com/services/', re.IGNORECASE), re.compile('^https?://[\\\\w.-]\*discord(app)?\\\\.com/api/webhooks/', re.IGNORECASE), re.compile('^https?://[\\\\w.-]+/[\\\\w/.-]\*\\\\?[^#]\*\\\\b(x-amz-signature|sig|signature|token|access_token|api[_-]?key|apikey|secret|password)=', re.IGNORECASE), re.compile('^https?://[^/@]\*:[^/@]\*@', re.IGNORECASE))*

holding it is the whole of the
permission, so printing it on a page is disclosing it. openloops’ scrubber catches
credential-shaped *text* (an inline password, an API key) and these are not that –
they are ordinary-looking https URLs whose path is the secret.

Best effort by construction, and the report’s sanitiser is still the second line. What
makes it worth having anyway is the direction of travel: before links were resolved,
a webhook sitting in a ledger had no path to a page that gets published off the
machine. Add a shape here when one is found; the cost of a false positive is one link
that renders as text.

* **Type:**
  URL shapes where the URL *is* the credential

### crowsnest.links.from_commits(text, context)

A bare commit sha, against the repository the session is working in.

Held to a hexadecimal run of at least seven characters that is not part of a longer
word, which is what git itself considers an abbreviated sha. A word that happens to be
seven hex letters (`decade`, `defaced`) is the false positive this accepts; it
costs a link nobody clicks, where the alternative – not linking shas at all – costs
the one reference a person most often wants to look up.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Link`](#crowsnest.links.Link)]

```pycon
>>> from_commits('fixed in 7d30838', {'repo_url': 'https://github.com/o/r'})[0].text
'r@7d30838'
```

### crowsnest.links.from_issue_refs(text, context)

A bare `#N`, resolved against the repository the session is working in.

This is the one that needs crowsnest. `#17` is the commonest reference a session
writes and the least resolvable on its own; the session’s working directory says which
repository it means, and the roster already knows the directory.

Nothing is produced without a `repo_url` in the context – a wrong repository is
worse than no link, because a link that goes somewhere plausible and wrong is one
nobody checks.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Link`](#crowsnest.links.Link)]

```pycon
>>> from_issue_refs('closes #17', {'repo_url': 'https://github.com/o/r'})[0].url
'https://github.com/o/r/issues/17'
>>> from_issue_refs('closes #17', {})
[]
```

### crowsnest.links.from_markdown_links(text, context)

`[label](url)` a session already wrote out in full, keeping the label it chose.

The best source available and the cheapest: a session that wrote a markdown link had
the whole reference in hand and named it for a reader. Nothing is inferred.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Link`](#crowsnest.links.Link)]

```pycon
>>> from_markdown_links('see [PR 27](https://github.com/o/r/pull/27)', {})[0].text
'PR 27'
```

### crowsnest.links.from_repo_refs(text, context)

`owner/repo#N`, which names its own repository and needs no context.

The issue-or-pull-request ambiguity is left as `issue`: GitHub redirects an issue
URL to the pull request when that is what the number is, so the link works either
way, and guessing would be a guess.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Link`](#crowsnest.links.Link)]

```pycon
>>> from_repo_refs('see i2mint/mergeset#12', {})[0].url
'https://github.com/i2mint/mergeset/issues/12'
```

### crowsnest.links.from_urls(text, context)

A bare URL, typed by where it points and labelled the way a person would say it.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Link`](#crowsnest.links.Link)]

```pycon
>>> [(l.type, l.text) for l in from_urls('see https://github.com/o/r/issues/3', {})]
[('issue', 'r#3')]
```

### crowsnest.links.github_ref(url)

A GitHub URL as `(kind, owner, repo, number)`; empty strings when it is not one.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> github_ref('https://github.com/i2mint/mergeset/pull/27')
('pr', 'i2mint', 'mergeset', '27')
>>> github_ref('https://github.com/o/r')
('repo', 'o', 'r', '')
>>> github_ref('https://example.org/x')
('', '', '', '')
>>> github_ref('https://www.github.com/o/r/issues/3')
('issue', 'o', 'r', '3')
```

### crowsnest.links.identity(url)

What two links have in common when they are the same reference.

A bare `#45` resolves to `.../issues/45` and a session that wrote the link out in
full may have written `.../pull/45` – **the same thing**, because GitHub redirects
an issue URL to the pull request when that is what the number is. Showing both is the
noise this feature exists to remove, so they collapse to one identity and the better
label wins. A discussion does *not* collapse into them: `discussions/45` is a
different object that happens to share a number.

Two spellings of one commit also collapse. A session writes `eb0774d0a` in one place
and the full forty characters in another, and both are the same commit; the longer
prefix wins on length, so they are compared on the shorter one’s length.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> identity('https://github.com/o/r/pull/45') == identity('https://github.com/o/r/issues/45')
True
>>> identity('https://github.com/o/r/discussions/45') == identity('https://github.com/o/r/issues/45')
False
>>> identity('https://WWW.github.com/O/R/issues/45') == identity('https://github.com/o/r/issues/45')
True
```

### crowsnest.links.kind_of(url)

What a bare URL points at, as one word.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> kind_of('https://github.com/o/r/pull/1'), kind_of('https://x.slack.com/archives/C1/p2')
('pr', 'slack')
>>> kind_of('https://claude.ai/code/artifact/abc'), kind_of('https://example.org')
('artifact', 'link')
```

### crowsnest.links.label_for(url, text='')

`text` when it says something, else a name derived from the URL.

The report calls this for references that reached it without a label – openloops’
own locators carry a URL and nothing else – so that nothing renders as a bare,
unclickable-looking blank.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> label_for('https://github.com/o/r/pull/27')
'r#27'
>>> label_for('https://github.com/o/r/pull/27', 'the release PR')
'the release PR'
```

### crowsnest.links.looks_like_a_secret(url)

Is this a URL that *is* a credential, rather than one that merely needs one?

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

```pycon
>>> looks_like_a_secret('https://hooks.slack.com/services/T0/B0/XXXX')
True
>>> looks_like_a_secret('https://github.com/o/r/issues/1')
False
```

### crowsnest.links.resolve(text, , context=None, resolvers=None, limit=12)

Every reference in `text`, as JSON-able links, best first and de-duplicated.

`context` is what the text cannot say for itself – today just `repo_url`, the
repository the session writing it works in, which is what makes a bare `#17`
resolvable. `resolvers` is the seam (see the module docstring); they run in order
and the first to claim a URL keeps its label, so a resolver placed first overrides
those after it.

The same reference appears many times in a session’s text, so a URL is kept once, at
the position it was first seen. Results come in **resolver order, not text order** –
the markdown links a session wrote out in full first, the shas it happened to mention
last – because a page shows the first few and those should be the best few.
`limit` bounds the result because this feeds a page meant to be read.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

```pycon
>>> [l['text'] for l in resolve('see #1 and o/r#2', context={'repo_url': 'https://github.com/o/r'})]
['r#2', 'r#1']
```

### crowsnest.links.without_written_out_links(text)

`text` with every markdown link and bare URL blanked, lengths preserved.

The context-dependent resolvers – the ones that attach a loose `#17` or a loose
sha to *this session’s* repository – must not fire inside a reference somebody
already wrote out in full. A ledger saying
`[#144](https://github.com/thorwhalen/priv/pull/144)` names priv’s 144; reading the
`#144` out of its label and resolving it against the session’s own repository
invents a link to a different project’s issue 144, which on a repository with six
hundred issues is a page that exists and is about something else.

Blanked rather than removed so that every offset in the string still means what it
meant – lookbehinds on either side of a match keep working.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> without_written_out_links('see [#1](https://github.com/o/r/pull/1) and #2')
'see                                     and #2'
```
