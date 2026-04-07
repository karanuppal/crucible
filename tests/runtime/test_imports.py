"""G1: Every shipped runtime module must import cleanly.

This is the gate that catches syntax errors and accidental import-time
breakage before they ship. Add new modules to MODULES below.
"""

import importlib
import os
import pkgutil
import pytest

import crucible.runtime as runtime_pkg


def _enumerate_runtime_modules():
    pkg_path = os.path.dirname(runtime_pkg.__file__)
    names = []
    for info in pkgutil.iter_modules([pkg_path]):
        if info.ispkg:
            continue
        names.append(f"crucible.runtime.{info.name}")
    return names


@pytest.mark.parametrize("module_name", _enumerate_runtime_modules())
def test_runtime_module_imports(module_name):
    """Every module under crucible.runtime must import without error."""
    importlib.import_module(module_name)


def test_at_least_seven_runtime_modules():
    """Sanity: ensure we're actually discovering modules, not silently passing 0."""
    mods = _enumerate_runtime_modules()
    assert len(mods) >= 7, f"expected ≥7 runtime modules, found {len(mods)}: {mods}"
