# crowsnest.jsonl

Decode one line of a JSONL file: orjson where it provably agrees with `json.loads`.

A transcript runs to megabytes and is decoded line by line on every poll, so the decoder
is the hot spot. `orjson` is several times faster than the standard library, and it is
optional: without it [`loads()`](#crowsnest.jsonl.loads) *is* `json.loads`.

With it, [`loads()`](#crowsnest.jsonl.loads) falls back to `json.loads` – the answer a caller got before –
for the two ways the decoders differ:

- a line orjson rejects. It rejects `NaN`, `Infinity` and `-Infinity`, a lone
  surrogate escape and a leading byte-order mark, which `json.loads` accepts; a line
  both reject raises `ValueError` as before.
- a line holding a run of [`WIDE`](#crowsnest.jsonl.WIDE) or more digits. orjson turns an integer beyond the
  64-bit range into a float; `json.loads` returns the exact `int`. (Every such
  integer has at least 20 digits; 19 also catches the edge of the range, and a
  nanosecond timestamp, at the price of a slower decode for those rare lines.)

Same policy as openloops’ transcript reader. Nothing else differs: duplicate keys keep
the last, key order is kept, and floats round the same way.

```pycon
>>> _usable(type('M', (), {'__version__': '3.9.15'})), _usable(type('M', (), {'__version__': '3.9.10'}))
(True, False)
>>> _usable(type('M', (), {'__version__': '3.11.0rc1'})), _usable(object())
(False, False)
>>> loads(b'{"a": [1, 2.5, null]}')
{'a': [1, 2.5, None]}
>>> loads(b'{"n": 123456789012345678901234567890}')['n']
123456789012345678901234567890
>>> loads('{nope')
Traceback (most recent call last):
  ...
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
```

### Module Attributes

| [`MIN_ORJSON`](#crowsnest.jsonl.MIN_ORJSON)   | orjson before this has no recursion limit and segfaults on a deeply nested line (CVE-2024-27454); `json.loads` raises `RecursionError` instead.   |
|---------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|
| [`WIDE`](#crowsnest.jsonl.WIDE)         | A run of this many digits sends a line to `json.loads` (see the module docstring).                                                                |

### Functions

| [`loads`](#crowsnest.jsonl.loads)(line)   | `json.loads(line)`, through orjson when that returns the same value.   |
|----------------------------------------------------------------|------------------------------------------------------------------------|

### crowsnest.jsonl.MIN_ORJSON *= (3, 9, 15)*

orjson before this has no recursion limit and segfaults on a deeply nested line
(CVE-2024-27454); `json.loads` raises `RecursionError` instead.

### crowsnest.jsonl.WIDE *= 19*

A run of this many digits sends a line to `json.loads` (see the module docstring).

### crowsnest.jsonl.loads(line)

`json.loads(line)`, through orjson when that returns the same value.

Raises `ValueError` for a line neither decoder reads.
