#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -e .env ]]; then
    echo '.env уже существует, файл оставлен без изменений.'
    exit 0
fi
umask 077
python3 - <<'PY'
import base64
import datetime
import os
import secrets

values = {
    "PUBLIC_URL": "http://localhost:3000",
    "OIDC_ISSUER": "http://localhost:8081/realms/reports-realm",
    "COOKIE_SECURE": "false",
    "BFF_CLIENT_SECRET": secrets.token_hex(24),
    "SESSION_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "AIRFLOW_FERNET_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "AIRFLOW_SECRET_KEY": secrets.token_hex(24),
    "CLICKHOUSE_ADMIN_PASSWORD": secrets.token_hex(24),
    "CLICKHOUSE_ETL_PASSWORD": secrets.token_hex(24),
    "CLICKHOUSE_REPORT_PASSWORD": secrets.token_hex(24),
    "ETL_START_DATE": (datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=7)).isoformat(),
}
with open('.env', 'x') as f:
    f.writelines(f'{key}={value}\n' for key, value in values.items())
print('Создан .env для локального стенда.')
PY
