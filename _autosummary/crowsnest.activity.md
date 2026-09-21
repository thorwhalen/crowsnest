# crowsnest.activity

What a session is doing right now, read from the tail of its transcript.

A transcript is append-only and can run to megabytes; the part that says what a session
is doing *now* is its last few kilobytes. So [`read_activity()`](#crowsnest.activity.read_activity) reads from the end,
widening the window only until it has seen one human prompt, and reports what it found:
what the session was last asked, what it last said, the tools it ran most recently, the
tool call that has not returned yet, and – the case a monitor exists for – a question it
has put to its human that nobody has answered.

What the transcript’s *content* means is `openloops.transcripts`’s business – which
`user` line is a person speaking and which is tooling, what the assistant’s last words
were, whether the turn ended – and `openloops.transcripts.parse_session()` is called
on the tail rather than that logic being written a second time. What this module adds is
the tool-level view that a dated digest has no use for and a live monitor cannot do
without.

[`read_turns()`](#crowsnest.activity.read_turns) is the deep path. It reads the whole file and pages backwards through
turns, for when the tail did not carry enough context and the alternative is spending a
turn of the watched session’s own context asking it.

```pycon
>>> read_activity('/nonexistent-file-for-doctest').last_user_prompt
''
```

### Module Attributes

| [`TAIL_BYTES`](#crowsnest.activity.TAIL_BYTES)    | How much of the file's end is read first.                                                        |
|----------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| [`RECENT_TOOLS`](#crowsnest.activity.RECENT_TOOLS)  | How many recent tool calls an [`Activity`](#crowsnest.activity.Activity) carries. |
| [`QUESTION_TOOL`](#crowsnest.activity.QUESTION_TOOL) | The tool Claude Code uses to put a structured question to its human.                             |

### Functions

| [`describe_tool`](#crowsnest.activity.describe_tool)(name, inputs, \*[, limit])     | One line naming a tool call: the tool, and the argument that says what it did.                   |
|-----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| [`load_records`](#crowsnest.activity.load_records)(path)                           | Every record in a transcript, tolerating blank and malformed lines.                              |
| [`read_activity`](#crowsnest.activity.read_activity)(path, \*[, session_id, ...])   | Read the tail of a transcript into an [`Activity`](#crowsnest.activity.Activity). |
| [`read_turns`](#crowsnest.activity.read_turns)(path, \*[, last, before])         | The last `last` turns of a transcript, oldest first; `before=N` pages back.                      |
| [`tail_records`](#crowsnest.activity.tail_records)(path, \*[, tail_bytes, enough]) | The records in the last `tail_bytes` of a transcript, widening until `enough`.                   |

### Classes

| [`Activity`](#crowsnest.activity.Activity)([session_id, last_event_at, ...])   | What one session is doing, as its transcript tail reads.                  |
|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`Turn`](#crowsnest.activity.Turn)(index, prompt, prompt_at, reply, ...)   | One exchange: a human prompt, what the assistant did, and its last words. |

### *class* crowsnest.activity.Activity(session_id='', last_event_at='', last_user_prompt='', last_prompt_at='', last_assistant_text='', last_text_at='', recent_tools=(), in_flight=(), pending_question='', turn_open=False, errored=False, git_branch='', tail_complete=True, tail_turns=0, locators=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What one session is doing, as its transcript tail reads. Flat and JSON-shaped.

`in_flight` lists tool calls with no result yet, oldest first: normally one, several
when calls were issued in parallel. `pending_question` is the first question of an
in-flight [`QUESTION_TOOL`](#crowsnest.activity.QUESTION_TOOL) call – a session waiting on a person.
`tail_complete` says whether the window reached the start of the file, which is what
makes the difference between “no prompt in the tail” and “no prompt at all”.
`tail_turns` is how many human prompts the window held: the session’s turn count
when `tail_complete` is true, and a floor otherwise. `locators` are the typed
references openloops found in the window – issues, pull requests – each a dict with
`type`, `url` and `text`, oldest first.

### crowsnest.activity.QUESTION_TOOL *= 'AskUserQuestion'*

The tool Claude Code uses to put a structured question to its human. A call to it with
no result yet is a session waiting on a person.

### crowsnest.activity.RECENT_TOOLS *= 6*

How many recent tool calls an [`Activity`](#crowsnest.activity.Activity) carries.

### crowsnest.activity.TAIL_BYTES *= 262144*

How much of the file’s end is read first. A turn of tool calls is a few kilobytes; a
quarter megabyte covers the last several turns of nearly every session and costs a
few milliseconds. The window doubles until it holds a human prompt.

### *class* crowsnest.activity.Turn(index, prompt, prompt_at, reply, reply_at, tools)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One exchange: a human prompt, what the assistant did, and its last words.

### crowsnest.activity.describe_tool(name, inputs, , limit=80)

One line naming a tool call: the tool, and the argument that says what it did.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> describe_tool('Bash', {'command': 'ls -la', 'description': 'List files'})
'Bash: List files'
>>> describe_tool('Read', {'file_path': '/a/b/c.py'})
'Read: c.py'
>>> describe_tool('AskUserQuestion', {'questions': [{'question': 'Ship it?'}]})
'AskUserQuestion: Ship it?'
>>> describe_tool('ListAgents', {})
'ListAgents'
```

### crowsnest.activity.load_records(path)

Every record in a transcript, tolerating blank and malformed lines.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### crowsnest.activity.read_activity(path, , session_id='', tail_bytes=262144, recent=6)

Read the tail of a transcript into an [`Activity`](#crowsnest.activity.Activity).

Costs the watched session nothing: the file is opened read-only and the session is
never signalled, messaged or otherwise made aware.

* **Return type:**
  [`Activity`](#crowsnest.activity.Activity)

### crowsnest.activity.read_turns(path, , last=5, before=None)

The last `last` turns of a transcript, oldest first; `before=N` pages back.

Reads the whole file. This is the deep path, taken on request when the tail did not
carry enough context – still cheaper than a turn of the watched session’s own.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Turn`](#crowsnest.activity.Turn)]

### crowsnest.activity.tail_records(path, \*, tail_bytes=262144, enough=<function \_has_prompt>)

The records in the last `tail_bytes` of a transcript, widening until `enough`.

Returns the records and whether the window reached the start of the file. The first
line of a window that starts mid-file is a fragment and is dropped.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]

```pycon
>>> tail_records('/nonexistent-file-for-doctest')
([], True)
```
