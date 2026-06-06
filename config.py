import os
import yaml
from pathlib import Path

_cfg = None

def get_config():
    global _cfg
    if _cfg is None:
        base = Path(__file__).parent

        # 1. Nicht-geheime Defaults (committet, immer vorhanden)
        with open(base / "config.defaults.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        # 2. Lokale config.yaml mit Secrets (gitignored, nur lokal vorhanden)
        local = base / "config.yaml"
        if local.exists():
            with open(local, encoding="utf-8") as f:
                cfg.update(yaml.safe_load(f) or {})

        # 3. Environment variables override yaml values (used on Render)
        env_map = {
            "SMTP_HOST":          "smtp_host",
            "SMTP_PORT":          "smtp_port",
            "SMTP_USER":          "smtp_user",
            "SMTP_PASSWORD":      "smtp_password",
            "SMTP_FROM":          "smtp_from",
            "SECRET_KEY":         "secret_key",
            "ADMIN_EMAIL":        "admin_email",
            "ADMIN_PASSWORD_HASH":"admin_password_hash",
            "CRON_SECRET":        "cron_secret",
            "RESEND_API_KEY":     "resend_api_key",
        }
        for env_key, cfg_key in env_map.items():
            val = os.environ.get(env_key)
            if val:
                cfg[cfg_key] = int(val) if cfg_key == "smtp_port" else val

        _cfg = cfg

    return _cfg
