BEGIN;

CREATE TABLE IF NOT EXISTS public.campaign_channel_registry (
 tenant_id varchar(64) NOT NULL,
 campaign_code varchar(128) NOT NULL,
 odoo_campaign_id bigint NOT NULL,
 parent_campaign_number integer NOT NULL REFERENCES public.campaign_registry(campaign_number),
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
);

INSERT INTO public.campaign_channel_registry(
 tenant_id,campaign_code,odoo_campaign_id,parent_campaign_number,channel,
 registry_status,activation_mode,allowlist_required,customer_traffic_allowed,
 policy_hash,approved_by
) VALUES (
 'COD','COD-WEB-OUT',6,400,'EMAIL','CANARY_READY','CANARY',true,false,
 '5b481054a18f64e23592d30cbe8d13877a7fbe79b41996ea14f83421d7524801',
 'OWNER_APPROVED_2026-08-22'
) ON CONFLICT(tenant_id,campaign_code,channel) DO UPDATE SET
 odoo_campaign_id=EXCLUDED.odoo_campaign_id,
 parent_campaign_number=EXCLUDED.parent_campaign_number,
 registry_status=EXCLUDED.registry_status,
 activation_mode=EXCLUDED.activation_mode,
 allowlist_required=EXCLUDED.allowlist_required,
 customer_traffic_allowed=EXCLUDED.customer_traffic_allowed,
 policy_hash=EXCLUDED.policy_hash,
 approved_by=EXCLUDED.approved_by,
 updated_at=now();

REVOKE ALL ON public.campaign_channel_registry FROM PUBLIC;
GRANT SELECT ON public.campaign_channel_registry TO mw_integration_api,mw_policy_engine,mw_reconciliation_worker;

COMMIT;
