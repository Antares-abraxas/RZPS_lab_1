#!/bin/bash
set -euo pipefail

PSQL_VARS=(
  -v ON_ERROR_STOP=1
  -v app_db="$APP_DB_NAME"
  -v app_user="$APP_DB_USER"
  -v app_password="$APP_DB_PASSWORD"
)

psql "${PSQL_VARS[@]}" --username "$POSTGRES_USER" --dbname postgres <<'EOSQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';

CREATE DATABASE :"app_db"
    TEMPLATE template0
    ENCODING 'UTF8'
    LOCALE 'ru_RU.UTF-8';

REVOKE ALL ON DATABASE :"app_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"app_db" TO :"app_user";
EOSQL

for script in 01_schema.sql 02_grants.sql 03_seed.sql; do
  psql "${PSQL_VARS[@]}" --username "$POSTGRES_USER" --dbname "$APP_DB_NAME" -f "/opt/sql/$script"
done
