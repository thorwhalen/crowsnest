"""Decode one line of a JSONL file: orjson where it provably agrees with ``json.loads``.

A transcript runs to megabytes and is decoded line by line on every poll, so the decoder
is the hot spot. ``orjson`` is several times faster than the standard library, and it is
optional: without it :func:`loads` *is* ``json.loads``.

With it, :func:`loads` falls back to ``json.loads`` -- the answer a caller got before --
for the two ways the decoders differ:

- a line orjson rejects. It rejects ``NaN``, ``Infinity`` and ``-Infinity``, a lone
  surrogate escape and a leading byte-order mark, which ``json.loads`` accepts; a line
  both reject raises ``ValueError`` as before.
- a line holding a run of :data:`WIDE` or more digits. orjson turns an integer beyond the
  64-bit range into a float; ``json.loads`` returns the exact ``int``. (Every such
  integer has at least 20 digits; 19 also catches the edge of the range, and a
  nanosecond timestamp, at the price of a slower decode for those rare lines.)

Same policy as openloops' transcript reader. Nothing else differs: duplicate keys keep
the last, key order is kept, and floats round the same way.

>>> loads(b'{"a": [1, 2.5, null]}')
{'a': [1, 2.5, None]}
>>> loads(b'{"n": 123456789012345678901234567890}')['n']
123456789012345678901234567890
>>> loads('{nope')
Traceback (most recent call last):
  ...
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
"""

from __future__ import annotations

import json
import re

try:  # optional: ``pip install crowsnest[fast]``
    import orjson
except ImportError:  # pragma: no cover - exercised by the monkeypatched test
    orjson = None

__all__ = ["WIDE", "loads"]

#: A run of this many digits sends a line to ``json.loads`` (see the module docstring).
WIDE = 19

#: Every digit byte to ``0`` and every other byte to ``x``: a run of ``WIDE`` digits is
#: then ``b"0" * WIDE`` inside the result, which ``in`` finds at memory speed. (A regex
#: for the same run costs more than orjson saves.)
_DIGITS_ONLY = bytes.maketrans(
    bytes(range(256)), bytes(48 if 48 <= b <= 57 else 120 for b in range(256))
)
_WIDE_RUN = b"0" * WIDE
_WIDE_TEXT = re.compile(rf"\d{{{WIDE}}}")


def _is_wide(line: bytes | str) -> bool:
    """Does ``line`` hold a run of :data:`WIDE` or more digits?

    >>> _is_wide(b'{"n": 1234567890123456789}'), _is_wide(b'{"n": 123456789012345678}')
    (True, False)
    >>> _is_wide('{"n": 1234567890123456789}'), _is_wide('{"n": 1, "m": 2}')
    (True, False)
    """
    if isinstance(line, (bytes, bytearray)):
        return _WIDE_RUN in line.translate(_DIGITS_ONLY)
    return _WIDE_TEXT.search(line) is not None


def loads(line: bytes | str):
    """``json.loads(line)``, through orjson when that returns the same value.

    Raises ``ValueError`` for a line neither decoder reads.
    """
    if orjson is not None and not _is_wide(line):
        try:
            return orjson.loads(line)
        except ValueError:  # orjson.JSONDecodeError is one; json decides
            pass
    return json.loads(line)
