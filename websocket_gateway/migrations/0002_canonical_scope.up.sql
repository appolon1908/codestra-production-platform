ALTER TABLE realtime_sessions ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE realtime_sessions ALTER COLUMN business_unit_id DROP NOT NULL;
ALTER TABLE realtime_sessions ALTER COLUMN vicidial_user DROP NOT NULL;
ALTER TABLE realtime_sessions ALTER COLUMN extension DROP NOT NULL;
ALTER TABLE realtime_events ALTER COLUMN user_id DROP NOT NULL;
DROP INDEX IF EXISTS ix_realtime_replay_scope;
CREATE INDEX ix_realtime_replay_scope
  ON realtime_events(tenant_id, campaign_id, agent_id, ordinal);
INSERT INTO websocket_schema_migrations(version) VALUES ('0002_canonical_scope')
ON CONFLICT (version) DO NOTHING;
