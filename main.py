from __future__ import annotations

import os
import sys


def main() -> int:
    if getattr(sys, "frozen", False):
        here = os.path.dirname(sys.executable)
        sys.path.insert(0, here)
        internal = getattr(sys, "_MEIPASS", "")
        if internal:
            sys.path.insert(0, internal)
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import shell
    return shell.run()


if __name__ == "__main__":
    sys.exit(main())
