"""Small helpers shared by the experiment scripts."""
import json
import sys
from contextlib import contextmanager

import numpy as np

from src.config import RESULTS_DIR


@contextmanager
def todo_guard(what):
    """Turn a NotImplementedError from an unfinished TODO into a clear message and exit code 2."""
    try:
        yield
    except NotImplementedError as e:
        print(f"\n[{what}] stopped: {e}. Fill in that TODO in src/ and run again.")
        sys.exit(2)


def save_json(name, obj):
    """Write obj to results/<name> (numpy types converted)."""
    RESULTS_DIR.mkdir(exist_ok=True)

    def default(o):
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, np.generic):
            return o.item()
        return str(o)

    path = RESULTS_DIR / name
    path.write_text(json.dumps(obj, indent=1, default=default))
    print(f"saved {path.relative_to(RESULTS_DIR.parent)}")
    return path
