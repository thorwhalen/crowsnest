# crowsnest.egress

The page’s sanitiser, made safe against text that an earlier clip has already cut (#83).

Several clips run on a row’s text *before* the page sees it: a tool call’s argument is cut
to 80 characters ([`crowsnest.activity.describe_tool()`](crowsnest.activity.html.md#crowsnest.activity.describe_tool)), a roster row’s prompt and last
words to 240 (`crowsnest.tools._clip()`), a reason to 200, and the page cuts its own
tile lines and raw asks. Each cut keeps a prefix and appends an ellipsis, and a credential
or home path cut that way is a shape no pattern in `openloops.egress` recognises:
`ghp_AAAA…` goes through `openloops.dashboard.Sanitizer.text()` untouched.

The rows are not changed: their clipped text is attention’s material, so cutting it
differently would resurface every item it touches. Instead the one choke point everything
reaches the page through, [`Sanitizer`](#crowsnest.egress.Sanitizer), drops each word an ellipsis ends before it
scrubs. A clip always cuts the last word it kept, so that is the only word that can be a
fragment. The price is that a word a person wrote before an ellipsis of their own is lost
too; a published line saying `Let me think…` reads `Let me …`, which loses nothing
anyone acts on.

Not for text that this module’s callers clip *after* sanitising ([`crowsnest.live.publishable()`](crowsnest.live.html.md#crowsnest.live.publishable)
does): its own ellipsis follows an already-clean word, and dropping that word would eat
every clipped line.

### Functions

| [`drop_cut_words`](#crowsnest.egress.drop_cut_words)(text)   | `text` without any word that an ellipsis ends; each ellipsis stays.   |
|-------------------------------------------------------------------------|-----------------------------------------------------------------------|

### Classes

| [`Sanitizer`](#crowsnest.egress.Sanitizer)([aliases])   | `openloops.dashboard.Sanitizer` that first drops the word an ellipsis ends.   |
|-------------------------------------------------------------------------|-------------------------------------------------------------------------------|

### *class* crowsnest.egress.Sanitizer(aliases=None)

Bases: `Sanitizer`

`openloops.dashboard.Sanitizer` that first drops the word an ellipsis ends.

```pycon
>>> Sanitizer().text('see ghp_' + 'A' * 20 + '…')
'see …'
>>> Sanitizer().text('a < b')
'a &lt; b'
```

#### text(value)

One field, safe to place in the document.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### crowsnest.egress.drop_cut_words(text)

`text` without any word that an ellipsis ends; each ellipsis stays.

```pycon
>>> drop_cut_words('Bash: use ghp_AAAAAAAA…')
'Bash: use …'
>>> drop_cut_words('Bash: use ghp_AAAAAAAA…; Read: /Users/an…')
'Bash: use …; Read: …'
>>> drop_cut_words('Read: notes.md')
'Read: notes.md'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
