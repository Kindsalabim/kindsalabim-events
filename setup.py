"""
Einmaliges Setup-Skript: Admin-Passwort setzen und Secret Key generieren.
Ausführen mit: python setup.py
"""
import yaml
import secrets
from pathlib import Path
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

config_path = Path(__file__).parent / "config.yaml"
with open(config_path, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

print(f"\n=== Setup: {cfg['app_name']} ===\n")
print(f"Admin-E-Mail: {cfg['admin_email']}")
password = input("Neues Admin-Passwort eingeben: ").strip()
if not password:
    print("Kein Passwort eingegeben. Abbruch.")
    exit(1)

cfg["admin_password_hash"] = pwd_context.hash(password)
cfg["secret_key"] = secrets.token_hex(32)

with open(config_path, "w", encoding="utf-8") as f:
    yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

print("\n✅ Passwort gesetzt und Secret Key generiert.")
print(f"   App starten mit: uvicorn main:app --reload")
print(f"   Admin-Login unter: http://localhost:8000/admin/login")
print(f"   Dienstleister-Portal: http://localhost:8000/portal/login\n")
