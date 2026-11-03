"""`python -m studio ...` (pythonw.exe -m studio worker serve runs the worker without a console window)."""

import os
import sys

# pythonw.exe has no console: sys.stdout/sys.stderr are None and any print (rich, uvicorn) would crash.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115

from .cli import app  # noqa: E402

app(prog_name="studio")
