-- Run once as postgres superuser: sudo -u postgres psql -f infra/postgres_bootstrap.sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'storyforge') THEN
    CREATE USER storyforge WITH PASSWORD 'change_me_now';
  END IF;
END
$$;

CREATE DATABASE storyforge OWNER storyforge;
GRANT ALL PRIVILEGES ON DATABASE storyforge TO storyforge;

\c storyforge
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for future full-text search on stories