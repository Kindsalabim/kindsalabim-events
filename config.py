import yaml
from pathlib import Path

_cfg = None

def get_config():
    global _cfg
    if _cfg is None:
        path = Path(__file__).parent / "config.yaml"
        with open(path, encoding="utf-8") as f:
            _cfg = yaml.safe_load(f)
    return _cfg
