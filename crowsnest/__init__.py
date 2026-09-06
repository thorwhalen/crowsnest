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
   not enough.
3. **The ask**: a running session can be *messaged* and will answer from its own
   context. That is a Claude Code feature, not a Python one, so it lives in the shipped
   skill (``crowsnest/data/skills/crowsnest/SKILL.md``) rather than here -- with the rule
   that says when it is worth a turn of someone else's context and when it is not.

And one stream: :func:`crowsnest.watch.events` yields a line every time a session starts,
exits, finishes a turn, or starts waiting on its human, so a monitor is told rather than
made to poll.

Everything here is read-only. Nothing sends, spawns, kills, or writes into another
session; the one write in the package is the skill installer, and it writes symlinks.

>>> from crowsnest import live_sessions, roster
>>> live_sessions(home='/nonexistent-dir-for-doctest')
[]
"""

from crowsnest.activity import Activity, Turn, read_activity, read_turns
from crowsnest.registry import LiveSession, live_sessions
from crowsnest.tools import resolve, roster, show, turns
from crowsnest.watch import events

__all__ = [
    "Activity",
    "LiveSession",
    "Turn",
    "events",
    "live_sessions",
    "read_activity",
    "read_turns",
    "resolve",
    "roster",
    "show",
    "turns",
]
