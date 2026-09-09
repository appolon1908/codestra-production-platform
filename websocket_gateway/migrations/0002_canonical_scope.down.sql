DELETE FROM websocket_schema_migrations WHERE version = '0002_canonical_scope';
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM realtime_sessions WHERE user_id IS NULL OR business_unit_id IS NULL
             OR vicidial_user IS NULL OR extension IS NULL)
     OR EXISTS (SELECT 1 FROM realtime_events WHERE user_id IS NULL) THEN
    RAISE EXCEPTION 'cannot restore legacy non-null scope while canonical rows exist';
  END IF;
END $$;
ALTER TABLE realtime_events ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE realtime_sessions ALTER COLUMN extension SET NOT NULL;
ALTER TABLE realtime_sessions ALTER COLUMN vicidial_user SET NOT NULL;
ALTER TABLE realtime_sessions ALTER COLUMN business_unit_id SET NOT NULL;
ALTER TABLE realtime_sessions ALTER COLUMN user_id SET NOT NULL;
DROP INDEX IF EXISTS ix_realtime_replay_scope;
CREATE INDEX ix_realtime_replay_scope
  ON realtime_events(tenant_id, user_id, agent_id, ordinal);
