from __future__ import annotations

import sys


def main() -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")

    from .application import LocalTrackerApplication

    return LocalTrackerApplication().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
