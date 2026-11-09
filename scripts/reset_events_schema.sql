-- DESTRUCTIF : supprime sources, events et event_sources (et leurs données).
-- À n'utiliser que pour passer de l'ancien schéma au nouveau, puis rejouer schema.sql :
--   psql "$DATABASE_URL" -f scripts/reset_events_schema.sql -f schema.sql
-- La table tasks est conservée. Faites une sauvegarde avant : pg_dump "$DATABASE_URL" > backup.sql
BEGIN;
DROP TABLE IF EXISTS event_sources, events, sources CASCADE;
COMMIT;
