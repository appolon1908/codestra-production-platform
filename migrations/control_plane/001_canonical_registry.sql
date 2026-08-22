BEGIN;
CREATE SCHEMA IF NOT EXISTS control_plane;

DO $$ BEGIN
  CREATE TYPE control_plane.sync_status AS ENUM
    ('DRAFT','VALIDATED','READY','SYNC_REQUESTED','SYNCING','VERIFYING','SYNCED',
     'FAILED','RETRY_PENDING','DEAD_LETTER','DRIFTED','RECONCILING');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS control_plane.campaign (
 id uuid PRIMARY KEY, tenant_id text NOT NULL, campaign_code text NOT NULL,
 name text NOT NULL, direction text NOT NULL,
 telephony_enabled boolean NOT NULL DEFAULT false,
 desired_state text NOT NULL CHECK (desired_state IN ('DRAFT','READY','ACTIVE','INACTIVE','SUSPENDED','ARCHIVED')),
 effective_state text, version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
 sync_status control_plane.sync_status NOT NULL DEFAULT 'DRAFT',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 last_reconciled_at timestamptz, UNIQUE (tenant_id,campaign_code));
CREATE TABLE IF NOT EXISTS control_plane.campaign_target (
 id uuid PRIMARY KEY,campaign_id uuid NOT NULL REFERENCES control_plane.campaign(id),
 target_system text NOT NULL CHECK(target_system IN ('ODOO','VICIDIAL','N8N','PROVISIONING','OTHER_APPROVED_TARGET')),
 external_id text,desired_state text NOT NULL,actual_state text,last_synced_version bigint,
 last_synced_at timestamptz,sync_status control_plane.sync_status NOT NULL DEFAULT 'DRAFT',
 error_code text,error_detail_safe text,created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),UNIQUE(campaign_id,target_system));
CREATE TABLE IF NOT EXISTS control_plane.agent (
 id uuid PRIMARY KEY,tenant_id text NOT NULL,username text NOT NULL,business_state text NOT NULL,
 desired_state text NOT NULL,actual_state text,version bigint NOT NULL DEFAULT 1 CHECK(version>0),
 sync_status control_plane.sync_status NOT NULL DEFAULT 'DRAFT',created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,username));
CREATE TABLE IF NOT EXISTS control_plane.agent_identity (
 id uuid PRIMARY KEY,agent_id uuid NOT NULL REFERENCES control_plane.agent(id),system text NOT NULL,
 identity_type text NOT NULL,external_id text NOT NULL,active boolean NOT NULL DEFAULT true,
 verified_at timestamptz,version bigint NOT NULL DEFAULT 1 CHECK(version>0),
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(system,identity_type,external_id),UNIQUE(agent_id,system,identity_type));
CREATE TABLE IF NOT EXISTS control_plane.extension (
 id uuid PRIMARY KEY,tenant_id text NOT NULL,extension_number text NOT NULL,asterisk_endpoint text,
 vicidial_phone text,desired_state text NOT NULL,actual_state text,version bigint NOT NULL DEFAULT 1,
 sync_status control_plane.sync_status NOT NULL DEFAULT 'DRAFT',created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),UNIQUE(tenant_id,extension_number));
CREATE TABLE IF NOT EXISTS control_plane.extension_assignment (
 id uuid PRIMARY KEY,extension_id uuid NOT NULL REFERENCES control_plane.extension(id),
 agent_id uuid NOT NULL REFERENCES control_plane.agent(id),desired_state text NOT NULL,actual_state text,
 version bigint NOT NULL DEFAULT 1,effective_from timestamptz NOT NULL,effective_until timestamptz,
 last_reconciled_at timestamptz,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX IF NOT EXISTS one_active_extension_owner ON control_plane.extension_assignment(extension_id)
 WHERE effective_until IS NULL AND desired_state='ACTIVE';
CREATE TABLE IF NOT EXISTS control_plane.membership (
 id uuid PRIMARY KEY,tenant_id text NOT NULL,campaign_id uuid NOT NULL REFERENCES control_plane.campaign(id),
 agent_id uuid NOT NULL REFERENCES control_plane.agent(id),desired_state text NOT NULL,actual_state text,
 role text NOT NULL,version bigint NOT NULL DEFAULT 1,sync_status control_plane.sync_status NOT NULL DEFAULT 'DRAFT',
 effective_from timestamptz NOT NULL,effective_until timestamptz,last_reconciled_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX IF NOT EXISTS one_active_membership ON control_plane.membership(campaign_id,agent_id,role)
 WHERE effective_until IS NULL AND desired_state='ACTIVE';

CREATE TABLE IF NOT EXISTS control_plane.idempotency (
 tenant_id text NOT NULL,operation text NOT NULL,idempotency_key text NOT NULL,request_hash text NOT NULL,
 response_json jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(tenant_id,operation,idempotency_key));
CREATE TABLE IF NOT EXISTS control_plane.sync_job (
 id uuid PRIMARY KEY,tenant_id text NOT NULL,entity_type text NOT NULL,entity_id uuid NOT NULL,
 entity_version bigint NOT NULL,operation text NOT NULL,status control_plane.sync_status NOT NULL,
 correlation_id uuid NOT NULL,idempotency_key text NOT NULL,attempt_count integer NOT NULL DEFAULT 0,
 max_attempts integer NOT NULL DEFAULT 5,error_code text,error_detail_safe text,
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,operation,idempotency_key));
CREATE TABLE IF NOT EXISTS control_plane.sync_step (
 id uuid PRIMARY KEY,job_id uuid NOT NULL REFERENCES control_plane.sync_job(id),step_name text NOT NULL,
 status text NOT NULL,attempt integer NOT NULL DEFAULT 0,started_at timestamptz,completed_at timestamptz,
 error_code text,error_detail_safe text,UNIQUE(job_id,step_name));
CREATE TABLE IF NOT EXISTS control_plane.sync_result (
 id uuid PRIMARY KEY,job_id uuid NOT NULL REFERENCES control_plane.sync_job(id),entity_version bigint NOT NULL,
 result_type text NOT NULL CHECK(result_type='RESULT'),payload_json jsonb NOT NULL,payload_hash text NOT NULL,
 verified boolean NOT NULL DEFAULT false,created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(job_id,payload_hash));
CREATE TABLE IF NOT EXISTS control_plane.event (
 id uuid PRIMARY KEY,schema_version text NOT NULL,correlation_id uuid NOT NULL,idempotency_key text NOT NULL,
 tenant_id text NOT NULL,event_kind text NOT NULL CHECK(event_kind IN ('COMMAND','EVENT','RESULT')),
 event_type text NOT NULL,entity_type text NOT NULL,entity_id uuid NOT NULL,entity_version bigint NOT NULL,
 payload_json jsonb NOT NULL,payload_hash text NOT NULL,occurred_at timestamptz NOT NULL,published_at timestamptz,
 UNIQUE(tenant_id,event_type,idempotency_key));
CREATE TABLE IF NOT EXISTS control_plane.event_delivery (
 id uuid PRIMARY KEY,event_id uuid NOT NULL REFERENCES control_plane.event(id),target text NOT NULL,
 status text NOT NULL DEFAULT 'PENDING',attempt_count integer NOT NULL DEFAULT 0,next_attempt_at timestamptz,
 last_error_code text,last_error_safe text,delivered_at timestamptz,UNIQUE(event_id,target));
CREATE TABLE IF NOT EXISTS control_plane.reconciliation_run (
 id uuid PRIMARY KEY,tenant_id text NOT NULL,scope text NOT NULL,status text NOT NULL,correlation_id uuid NOT NULL,
 started_at timestamptz NOT NULL,completed_at timestamptz,difference_count integer NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS control_plane.reconciliation_difference (
 id uuid PRIMARY KEY,run_id uuid NOT NULL REFERENCES control_plane.reconciliation_run(id),entity_type text NOT NULL,
 entity_id uuid NOT NULL,target_system text NOT NULL,drift_code text NOT NULL,risk text NOT NULL,
 desired_json jsonb NOT NULL,actual_json jsonb NOT NULL,remediation_status text NOT NULL DEFAULT 'OPEN',
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS control_plane.dead_letter (
 id uuid PRIMARY KEY,job_id uuid NOT NULL UNIQUE REFERENCES control_plane.sync_job(id),entity_type text NOT NULL,
 entity_id uuid NOT NULL,entity_version bigint NOT NULL,error_code text NOT NULL,error_detail_safe text,
 attempt_count integer NOT NULL,first_failure_at timestamptz NOT NULL,last_failure_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS control_plane.audit (
 id uuid PRIMARY KEY,tenant_id text NOT NULL,actor_type text NOT NULL,actor_id text NOT NULL,action text NOT NULL,
 entity_type text NOT NULL,entity_id uuid NOT NULL,entity_version bigint,correlation_id uuid NOT NULL,
 metadata_json jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now());

-- Tenant context is set by authenticated middleware after Kong authorization.
ALTER TABLE control_plane.campaign ENABLE ROW LEVEL SECURITY;
ALTER TABLE control_plane.agent ENABLE ROW LEVEL SECURITY;
ALTER TABLE control_plane.membership ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS campaign_tenant ON control_plane.campaign;
CREATE POLICY campaign_tenant ON control_plane.campaign USING (tenant_id=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS agent_tenant ON control_plane.agent;
CREATE POLICY agent_tenant ON control_plane.agent USING (tenant_id=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS membership_tenant ON control_plane.membership;
CREATE POLICY membership_tenant ON control_plane.membership USING (tenant_id=current_setting('app.tenant_id',true));

COMMIT;
