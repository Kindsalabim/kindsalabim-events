import os
import yaml
from pathlib import Path

_cfg = None

def get_config():
    global _cfg
    if _cfg is None:
        path = Path(__file__).parent / "config.yaml"
        with open(path, encoding="utf-8") as f:
            _cfg = yaml.safe_load(f)

        # Environment variables override yaml values (used on Render)
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
                _cfg[cfg_key] = int(val) if cfg_key == "smtp_port" else val

    return _cfg
