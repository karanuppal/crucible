# astropy__astropy-14309

- Source: SWE-bench Verified
- Repo: `astropy/astropy`
- Base commit: `cdb66059a2feb44ee49021874605ba90801f9986`
- Difficulty: `<15 min fix`
- Category: edge-case bug
- Focus: `io.registry` / FITS format detection

## FAIL_TO_PASS

- `astropy/io/fits/tests/test_connect.py::test_is_fits_gh_14305`

## Problem statement

IndexError: tuple index out of range in identify_format (io.registry)

### Description

Cron tests in HENDRICS using identify_format have started failing in `devdeps` with an `IndexError` in `astropy.io.fits.connect.is_fits()` when `identify_format("write", Table, "bububu.ecsv", None, [], {})` is called.

The reported behavior suggests a regression where a path without a FITS extension now falls through to `isinstance(args[0], ...)` even when no positional object argument exists.

### Reproduction snippet

```python
from astropy.io.registry import identify_format
from astropy.table import Table

identify_format("write", Table, "bububu.ecsv", None, [], {})
```

Expected: no `IndexError`.
