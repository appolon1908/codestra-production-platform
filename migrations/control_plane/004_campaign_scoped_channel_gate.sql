BEGIN;

DO $migration$
DECLARE
 campaign_id_type text;
BEGIN
 SELECT format_type(a.atttypid,a.atttypmod)
 INTO campaign_id_type
 FROM pg_attribute a
 WHERE a.attrelid='control_plane.campaign'::regclass
   AND a.attname='id'
   AND NOT a.attisdropped;

 IF campaign_id_type IS NULL THEN
  RAISE EXCEPTION 'control_plane.campaign.id is required';
 END IF;

 EXECUTE format($ddl$
CREATE TABLE IF NOT EXISTS control_plane.campaign_channel_registry (
 tenant_id varchar(64) NOT NULL,
 campaign_code varchar(128) NOT NULL,
 odoo_campaign_id bigint NOT NULL,
 parent_campaign_id %s NOT NULL REFERENCES control_plane.campaign(id),
 channel varchar(16) NOT NULL CHECK(channel IN ('EMAIL','SMS','VOICE')),
 registry_status varchar(32) NOT NULL CHECK(registry_status IN ('PROPOSED_DISABLED','CANARY_READY','ACTIVE','SUSPENDED')),
 activation_mode varchar(16) NOT NULL CHECK(activation_mode IN ('DISABLED','CANARY','FULL')),
 allowlist_required boolean NOT NULL DEFAULT true,
 customer_traffic_allowed boolean NOT NULL DEFAULT false,
 policy_hash varchar(64) NOT NULL,
 approved_by varchar(128) NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,campaign_code,channel),
 CHECK(registry_status <> 'CANARY_READY' OR
       (activation_mode='CANARY' AND allowlist_required AND NOT customer_traffic_allowed))
)
$ddl$,campaign_id_type);
END
$migration$;

INSERT INTO control_plane.campaign_channel_registry(
 tenant_id,campaign_code,odoo_campaign_id,parent_campaign_id,channel,
 registry_status,activation_mode,allowlist_required,customer_traffic_allowed,
 policy_hash,approved_by
) SELECT
 'COD','COD-WEB-OUT',6,id,'EMAIL','CANARY_READY','CANARY',true,false,
 '5b481054a18f64e23592d30cbe8d13877a7fbe79b41996ea14f83421d7524801',
 'OWNER_APPROVED_2026-08-22'
 FROM control_plane.campaign
 WHERE tenant_id='COD' AND campaign_code='COD-WEB-OUT'
 ON CONFLICT(tenant_id,campaign_code,channel) DO NOTHING;

DO $required_gate$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM control_plane.campaign_channel_registry
  WHERE tenant_id='COD' AND campaign_code='COD-WEB-OUT' AND channel='EMAIL'
 ) THEN
  RAISE EXCEPTION 'required COD-WEB-OUT EMAIL channel gate was not created';
 END IF;
END
$required_gate$;

REVOKE ALL ON control_plane.campaign_channel_registry FROM PUBLIC;
GRANT SELECT ON control_plane.campaign_channel_registry TO mw_integration_api,mw_policy_engine,mw_reconciliation_worker;

COMMIT;
