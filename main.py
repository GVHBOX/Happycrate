from __future__ import annotations

import sys

from app import shell


def main() -> int:
    return shell.run()


if __name__ == "__main__":
    sys.exit(main())
