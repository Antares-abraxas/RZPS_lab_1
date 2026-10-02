#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname postgres \
     -v app_db="$APP_DB_NAME" \
     -v app_user="$APP_DB_USER" \
     -v app_password="$APP_DB_PASSWORD" <<'EOSQL'

CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';

CREATE DATABASE :"app_db"
    TEMPLATE template0
    ENCODING 'UTF8'
    LOCALE 'ru_RU.UTF-8';

REVOKE ALL ON DATABASE :"app_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"app_db" TO :"app_user";

\connect :"app_db"
GRANT USAGE ON SCHEMA public TO :"app_user";
EOSQL
