#!/usr/bin/env python
import os
import sys
from pathlib import Path


def main() -> None:
    # Python puts THIS file's directory on sys.path, not the project root, so the
    # `App.*` package this project is addressed by would not be importable. Every
    # other entry point (Servers/Server.py, portal/task_engine.py) puts the root on
    # the path for the same reason.
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "App.Frontend.webapp.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
