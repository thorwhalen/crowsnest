# crowsnest — dev notes

Seams (one kwarg each): `home=` (the Claude Code config dir; a synced copy of another
machine's is the replacement — `xa.hosts.ssh.SSHHost` pulls one); `is_alive=` (pid check;
`xa.claude_fs.ephemeral_session_alive` is the /proc-aware replacement); `spawner=` in
`crowsnest.spawn.spawn` (starts the built `claude` argv somewhere a person can find it;
`xa spawn` is the pointed replacement, adding hosts and a phone web UI). Surfaces built:
CLI (`cw`), shipped skill + subagent. Not seams: rendering, the status vocabulary, tail size.

- Core is `crowsnest/tools.py` (JSON dicts in and out); `__main__.py` renders only.
- Transcript *content* parsing is openloops' (`parse_session`); do not re-implement it here.
- The skill is at `crowsnest/data/skills/crowsnest/`; `.claude/skills/crowsnest` is a symlink to it.
