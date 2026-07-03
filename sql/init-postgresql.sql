\set ON_ERROR_STOP on

-- Usage (run as a PostgreSQL administrator):
-- psql -v webfetch_password='replace-with-a-strong-password' -f sql/init-postgresql.sql

\if :{?webfetch_password}
\else
  \echo 'ERROR: webfetch_password is required'
  \quit
\endif

SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'webfetch') AS role_exists \gset
\if :role_exists
  ALTER ROLE webfetch WITH LOGIN PASSWORD :'webfetch_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
\else
  CREATE ROLE webfetch WITH LOGIN PASSWORD :'webfetch_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
\endif

SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'webfetch') AS database_exists \gset
\if :database_exists
  \echo 'Database webfetch already exists'
\else
  CREATE DATABASE webfetch OWNER webfetch ENCODING 'UTF8' TEMPLATE template0;
\endif

\connect webfetch
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE webfetch TO webfetch;
GRANT USAGE, CREATE ON SCHEMA public TO webfetch;

ALTER DEFAULT PRIVILEGES FOR ROLE webfetch IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO webfetch;
ALTER DEFAULT PRIVILEGES FOR ROLE webfetch IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO webfetch;

