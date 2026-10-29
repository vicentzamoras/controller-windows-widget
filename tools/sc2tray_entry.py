"""PyInstaller entry point (it needs a script, not `python -m sc2tray`)."""
import sys

from sc2tray.__main__ import main

sys.exit(main())
