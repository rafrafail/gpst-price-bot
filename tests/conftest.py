"""Bootstrap pytest's configured temporary directory in a fresh checkout."""
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    basetemp = config.getoption("basetemp")
    if basetemp:
        # pytest creates/cleans basetemp itself, but expects its parent to exist.
        Path(basetemp).parent.mkdir(parents=True, exist_ok=True)
