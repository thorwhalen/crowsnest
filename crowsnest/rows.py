"""How an item's row is built and hashed: one value, taken whole by every surface that pins it.

The attention store pins what a person saw to a *revision* of a row
(:mod:`crowsnest.attention`), and three surfaces compute that revision on their own: the
report renders it into the page (:func:`crowsnest.tools.report`), the attention verbs pin
it (:func:`crowsnest.tools.seen` and the rest), and the watcher computes it again to say
that an item put off has woken (:func:`crowsnest.watch.attention_wakes`). They agree only
if they build the row the same way and hash it the same way. When they did not, nothing
said so: a marked item read as changed on the page, or woke on the watcher's first tick
(#74). Each argument that builds a row was threaded through each surface by hand, and the
review of that fix found one still missing (#78).

So how a row is built and hashed is one value, :class:`RowContext`. Each of those surfaces
takes it as one keyword argument, ``row_context=``, and hands it on whole, and nothing
outside this module reads its fields. A new way to build a row is a field here, read in
:meth:`RowContext.rows` or :meth:`RowContext.rev`, and every surface has it.

The default is :func:`dflt_row_context`: the config file's ``[report]`` table
(:func:`crowsnest.config.report_settings`) names the ledger directory, so
``crowsnest report``, the verbs and ``crowsnest watch`` agree without the same
``--ledger-dir`` typed three times.

.. code-block:: toml

    [report]
    ledger_dir = "~/sync/crowsnest/ledger"   # absolute, or starting with ~

The default context builds and hashes exactly as the loose arguments' defaults did, so no
stored id or revision changes with it.

>>> RowContext(owner='ana').rev({'status': 'busy'}) == RowContext().rev({'status': 'busy'})
True
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from crowsnest import attention as _attention
from crowsnest.config import report_settings

__all__ = ["RowContext", "dflt_row_context"]


@dataclass(frozen=True)
class RowContext:
    """How a row is built and hashed. Build one once; hand the same one to every surface.

    ``ledger_dir`` is where the ledgers are (``None``: ``<data dir>/ledger``);
    ``resolvers`` turn what a session wrote into links (:mod:`crowsnest.links`);
    ``verdicts`` and ``owner`` classify it (:mod:`crowsnest.triage`); ``identity`` and
    ``material`` name the item and say what counts as a change to it
    (:mod:`crowsnest.attention`). ``None`` is each module's own default, so
    ``RowContext()`` builds and hashes as those modules do on their own.

    ``resolvers`` and ``verdicts`` are kept as tuples: a generator handed in would be spent
    on the first row of a page, and every row after it would be built without them.
    """

    ledger_dir: str | Path | None = None
    resolvers: tuple | None = None
    verdicts: tuple | None = None
    owner: str = ""
    identity: Callable[[Mapping], Iterable[str]] | None = None
    material: Callable[[Mapping], Iterable] | None = None

    def __post_init__(self) -> None:
        for name in ("resolvers", "verdicts"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    @classmethod
    def from_config(cls, *, path: str | Path | None = None, **changes) -> RowContext:
        """The context the config file describes, with ``changes`` on top.

        ``RowContext.from_config(ledger_dir=flag)`` is what a ``--ledger-dir`` flag means:
        the config file's context, with that one directory instead.
        """
        return cls(**{"ledger_dir": report_settings(path=path).ledger_dir, **changes})

    def pages(self, labels: Iterable[str]) -> dict:
        """Each named session's ledger page, read once (an empty page for none)."""
        from crowsnest.tools import _ledgers_for

        return _ledgers_for(labels, self.ledger_dir)

    def rows(
        self,
        found: Iterable,
        *,
        home_dir: Path | None = None,
        pages: Mapping | None = None,
        links: bool = True,
        triage: bool = True,
    ) -> list[dict]:
        """The rows the report shows for the live sessions ``found``, in their order.

        The one place a row is built: the roster's clipping and link cap, then its triage
        verdict. ``home_dir`` is what each row's ``open_command`` pins; ``pages`` are the
        ledgers already read (:meth:`pages`), read here when not given. ``links=False``
        and ``triage=False`` are the report's switches; the verbs and the watcher build
        with both on, because the page they must agree with does.
        """
        from crowsnest.said import with_said
        from crowsnest.tools import _roster_row
        from crowsnest.triage import classify_row

        found = list(found)
        pages = self.pages({s.label for s in found}) if pages is None else pages
        built = []
        for s in found:
            page = pages.get(s.label)
            row = with_said(
                _roster_row(
                    s,
                    links=links,
                    ledger_dir=self.ledger_dir,
                    resolvers=self.resolvers,
                    page=page,
                    home_dir=home_dir,
                )
            )
            if triage:
                verdict = classify_row(
                    row, ledger=page or {}, verdicts=self.verdicts, owner=self.owner
                )
                # Set again once the verdict is known, so the row and its verdict agree
                # about when the thing it quotes was said.
                row = with_said({**row, "verdict": verdict})
            built.append(row)
        return built

    def row(
        self,
        session: str,
        *,
        home: str | Path | None = None,
        all_homes: bool = False,
        config: str | Path | None = None,
    ) -> dict:
        """The row the report shows for ``session``, a reference as
        :func:`crowsnest.tools.resolve` takes one. Raises ``KeyError`` when none matches.
        """
        from crowsnest.tools import _home_to_pin, resolve

        s = resolve(session, home=home, all_homes=all_homes, config=config)
        pin = _home_to_pin(home=home, all_homes=all_homes, config=config)
        return self.rows([s], home_dir=pin)[0]

    def item(self, row: Mapping) -> str:
        """The row's item id (:func:`crowsnest.attention.item_id`)."""
        return _attention.item_id(row, identity=self.identity)

    def rev(self, row: Mapping) -> str:
        """The row's revision (:func:`crowsnest.attention.fingerprint`)."""
        return _attention.fingerprint(row, material=self.material)


def dflt_row_context(*, config: str | Path | None = None) -> RowContext:
    """The context a surface uses when it is given none: the config file's.

    >>> dflt_row_context(config='/nonexistent-config-for-doctest') == RowContext()
    True
    """
    return RowContext.from_config(path=config)
