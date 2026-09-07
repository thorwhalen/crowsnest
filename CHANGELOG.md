# Changelog

Newest first. The version is bumped by CI on every merge to `main`, so one merge is one entry.

## 0.0.17 (2026-09-07)

- `watch` no longer streams an `idle_prompt` notification as `needs-you`.
- README: what the hooks add.

## 0.0.15 to 0.0.16 (2026-09-07)

- `report --fragment`: the artifact-ready page without the document wrapper (#19).
- The report imports the stylesheet and the sanitizer from openloops 0.1.9 instead of copying them.

## 0.0.12 to 0.0.14 (2026-09-06)

- `init --hooks` puts the roster-on-start hook in the crowsnest directory's own project settings, never user-wide.
- Dev notes in `.claude/CLAUDE.md`.

## 0.0.5 to 0.0.11 (2026-09-06)

- Several homes in one roster and one `watch` (#1).
- `crowsnest spawn` (#2).
- `crowsnest report`, the phone-readable page in the openloops dashboard design (#3).
- Per-session ledgers and hook-fed `stopped` / `needs-you` events (#7).
- `crowsnest init`, the operating-model `CLAUDE.md`, the `crowsnest-dispatch`, `crowsnest-report` and `crowsnest-worker` skills, `crowsnest brief` (#6, #8).
- Registry polish: `shell` status, background rows, stale waiting detail, Windows liveness, turn count (#5).

## 0.0.2 (2026-09-06)

- First release: the roster, `show`, `turns`, `watch`, and the `crowsnest` skill with the `crowsnest-scout` subagent.
