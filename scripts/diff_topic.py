from importlib import import_module
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_module = import_module("scripts.topic_tools.diff_topic")
sys.modules[__name__] = _module
globals().update(_module.__dict__)

if __name__ == "__main__":
    raise SystemExit(_module.main())
