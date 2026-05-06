#!/bin/bash
# PostgreSQL initialisation — runs once at container first boot
# Creates a least-privilege app user that n8n connects with day-to-day
# The admin user (POSTGRES_USER) is only used by this init script

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER ${POSTGRES_NON_ROOT_USER} WITH PASSWORD '${POSTGRES_NON_ROOT_PASSWORD}';
    GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_NON_ROOT_USER};
    GRANT ALL ON SCHEMA public TO ${POSTGRES_NON_ROOT_USER};
EOSQL
