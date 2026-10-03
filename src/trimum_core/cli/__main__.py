"""Allow running the CLI with ``python -m trimum_core.cli``."""

from __future__ import annotations

import sys

from . import main


if __name__ == "__main__":
    sys.exit(main())
