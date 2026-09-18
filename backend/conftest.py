"""Test configuration.

Two things every test run needs and no test should have to remember:
 - the mock LLM provider, so the suite never depends on a running Ollama or a
   Groq key;
 - a throwaway ledger, so running the tests never writes into the developer's
   real skyassist.db.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ["LLM_PROVIDER"] = "mock"

_TMP_DB = Path(tempfile.gettempdir()) / "skyassist_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["DB_PATH"] = str(_TMP_DB)
