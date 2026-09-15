# crowsnest.paths

Where crowsnest keeps what is not code: the data directory, and nothing else.

Ledgers, the event log, and anything else the package writes live under one directory
outside any repository, so that an app directory holds only code and build output. The
directory is chosen the way openloops chooses its store: an explicit environment variable
wins, then the XDG data home, then `~/.local/share`.

Nothing is written into the directory itself; each kind of data hangs off it in its own
subdirectory or file (`ledger/`, `events.jsonl`), owned by the module that writes it.
This module exists so that those modules agree on the root without importing each other.

```pycon
>>> import os
>>> os.environ['CROWSNEST_DATA_DIR'] = '/x/y'
>>> data_dir().as_posix()
'/x/y'
>>> del os.environ['CROWSNEST_DATA_DIR']
```

### Module Attributes

| [`DATA_DIR_ENV_VAR`](#crowsnest.paths.DATA_DIR_ENV_VAR)   | Overrides the data directory outright.   |
|---------------------------------------------------------------------|------------------------------------------|

### Functions

| [`data_dir`](#crowsnest.paths.data_dir)([path])   | The data directory: `path`, else `$CROWSNEST_DATA_DIR`, else XDG, else `~/.local/share/crowsnest`.   |
|---------------------------------------------------------------------|------------------------------------------------------------------------------------------------------|

### crowsnest.paths.DATA_DIR_ENV_VAR *= 'CROWSNEST_DATA_DIR'*

Overrides the data directory outright. Tests and unusual installs set it.

### crowsnest.paths.data_dir(path=None)

The data directory: `path`, else `$CROWSNEST_DATA_DIR`, else XDG, else `~/.local/share/crowsnest`.

Returns the path without creating it; the writer that needs it creates it.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
