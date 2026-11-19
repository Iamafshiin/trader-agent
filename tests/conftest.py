import os
import sys
from pathlib import Path
from typing import Any

import appdirs

STORE = Path(__file__).resolve().parent.parent / ".crewai"


def _user_data_dir(name: Any = None, author: Any = None, *args: Any, **kwargs: Any) -> str:
    return str(STORE / str(author) / str(name))


if sys.platform == "win32":
    os.environ["LOCALAPPDATA"] = str(STORE)
    appdirs.user_data_dir = _user_data_dir
