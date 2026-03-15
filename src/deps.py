"""
deps.py — Shared dependencies for Budget Tracker routers.

Provides the Jinja2 templates instance and src_path so routers can
import them without creating circular dependencies with main.py.

All routers should import `templates` and `src_path` from here rather
than from main.py.
"""

import sys
from pathlib import Path

from fastapi.templating import Jinja2Templates

# Ensure src/ is on the path for all module imports
src_path = Path(__file__).resolve().parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

templates = Jinja2Templates(directory=src_path / "templates")
