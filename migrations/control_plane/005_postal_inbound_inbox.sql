BEGIN;

CREATE TABLE IF NOT EXISTS control_plane.postal_inbound_event (
 provider_event_id text PRIMARY KEY,
 tenant_id text NOT NULL,
 request_hash varchar(64) NOT NULL,
 correlation_id text NOT NULL,
 status varchar(24) NOT NULL CHECK(status IN ('PROCESSING','COMPLETED','FAILED')),
 result_json jsonb,
 error_detail_safe text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS postal_inbound_event_tenant_status
 ON control_plane.postal_inbound_event(tenant_id,status,updated_at);

REVOKE ALL ON control_plane.postal_inbound_event FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON control_plane.postal_inbound_event TO codestra_control_plane_runtime;
ALTER TABLE control_plane.postal_inbound_event ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS postal_inbound_event_tenant ON control_plane.postal_inbound_event;
CREATE POLICY postal_inbound_event_tenant ON control_plane.postal_inbound_event
 USING (tenant_id=current_setting('app.tenant_id',true))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true));

COMMIT;
