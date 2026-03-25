"""Config path must not depend on the process working directory."""

from pathlib import Path

import blaster.config as config_mod
from blaster.config import _default_config_path


def test_default_config_path_is_package_relative() -> None:
    """Default config is next to the project root (parent of the blaster package)."""
    expected = Path(config_mod.__file__).resolve().parent.parent / "config.yaml"
    assert _default_config_path() == expected
