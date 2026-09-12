"""One session that watches the others.

A machine running many Claude Code sessions has a question nobody answers: *what are they
all doing, and which of them needs me?* Each session knows only itself, the terminal tabs
are silent until you click them, and the answer lives in forty scrollbacks.

``crowsnest`` reads what Claude Code already writes -- the registry it keeps for every
running session, and the transcript each session appends to -- and answers in three
tiers, cheapest first:

1. **The roster** (:func:`crowsnest.tools.roster`): who is alive, busy, idle or waiting,
   where, since when. Instant; no transcript is read.
2. **The activity** (:func:`crowsnest.tools.show`, :func:`crowsnest.tools.turns`): what a
   session was last asked, what it last said, the tool it is running now, the question
   it is waiting on -- read from the tail of its transcript, which costs the watched
   session nothing and never interrupts it. ``turns`` pages further back when the tail is
   not enough, and :func:`crowsnest.tools.brief` looks up openloops' dated digest of a
   session without reading a transcript at all.
3. **The ask**: a running session can be *messaged* and will answer from its own
   context. That is a Claude Code feature, not a Python one, so it lives in the shipped
   skills (``crowsnest/data/skills/``) rather than here -- with the rules that say when it
   is worth a turn of someone else's context, how a corpus of work is handed to a session,
   and how the watching session stays small enough to be cleared at any moment.
   :mod:`crowsnest.init` is what sets a session up to live by them.

And one stream: :func:`crowsnest.watch.events` yields a line every time a session starts,
exits, finishes a turn, or starts waiting on its human, so a monitor is told rather than
made to poll. When the user has wired ``crowsnest hook`` onto Claude Code's ``Stop`` and
``Notification`` hooks (:mod:`crowsnest.hook`), those two moments are pushed into the
stream as they happen instead of being noticed a poll later.

Across all three tiers runs one relation the registry does not record: **who started
whom** (:mod:`crowsnest.lineage`). A fleet of forty reads as a list of forty until the
six that are one dispatcher's children are drawn as six children;
:func:`crowsnest.spawn.spawn` therefore writes down its own caller at the moment it
creates a session, when the answer is free and certain, and
:func:`crowsnest.tools.lineage` reads the forest back. What older sessions left behind is
recovered once, and marked as the inference it is, by
:func:`crowsnest.tools.backfill_lineage`.

Between the roster and the transcript there is a fourth thing, the only one crowsnest
authors: the **ledger** (:mod:`crowsnest.ledger`), one small markdown file per session,
holding what it was last asked and said, what it decided, and what it still needs from a
human. A session writes its own; a watcher reads it and survives being cleared.

Reading the others is the whole point, but the watching session also needs to *create*
the sessions it will then watch: :func:`crowsnest.spawn.spawn` starts one, named, in a
directory, and waits for the registry to see it.

Those are the writes, and they are all of them: a session started, and files that are
crowsnest's own and live outside any repository -- the ledgers, the hook event log, the
spawn records (all three under :func:`crowsnest.paths.data_dir`), and the symlinks the
skill installer makes.
crowsnest never sends into, kills, or writes into a session that already exists.

>>> from crowsnest import live_sessions, roster
>>> live_sessions(home='/nonexistent-dir-for-doctest')
[]
"""

from crowsnest.activity import Activity, Turn, read_activity, read_turns
from crowsnest.ledger import list_ledgers, read_ledger, update_ledger
from crowsnest.registry import LiveSession, live_sessions
from crowsnest.spawn import spawn

# `crowsnest.lineage` stays a *module* in this namespace, reached as
# `crowsnest.lineage.graph` / `.SpawnEdge`. It is not re-exported as a function, because
# the verb a surface calls is `crowsnest.tools.lineage` and two names at two altitudes
# for one feature is one too many. (`spawn` is the one place where a verb already shadows
# its module -- do not add a second.) It is also not imported here: `crowsnest hook`
# pays this module's import on every turn of every session and never uses it, so
# `spawn.spawn` and `tools.lineage` import it when they are called.
from crowsnest.tools import backfill_lineage, brief, resolve, roster, show, turns
from crowsnest.watch import events

__all__ = [
    "Activity",
    "LiveSession",
    "Turn",
    "backfill_lineage",
    "brief",
    "events",
    "list_ledgers",
    "live_sessions",
    "read_activity",
    "read_ledger",
    "read_turns",
    "resolve",
    "roster",
    "show",
    "spawn",
    "turns",
    "update_ledger",
]
