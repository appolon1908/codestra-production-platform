BEGIN;

ALTER TABLE public.event_deliveries ADD COLUMN IF NOT EXISTS lease_owner text;
ALTER TABLE public.event_deliveries ADD COLUMN IF NOT EXISTS lease_token text;
ALTER TABLE public.event_deliveries ADD COLUMN IF NOT EXISTS lease_expires_at double precision;
CREATE INDEX IF NOT EXISTS event_deliveries_claim_due
  ON public.event_deliveries(state,next_attempt,lease_expires_at,target);

ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS lease_owner text;
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS lease_token text;
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS lease_expires_at double precision;
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS next_attempt double precision NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS messages_claim_due
  ON public.messages(status,next_attempt,lease_expires_at,provider);

CREATE TABLE IF NOT EXISTS public.realtime_session_nonce(
  nonce_hash text PRIMARY KEY,
  tenant_id text NOT NULL,
  agent_id text NOT NULL,
  campaign_id text NOT NULL,
  issued_at double precision NOT NULL,
  expires_at double precision NOT NULL,
  consumed_at double precision,
  source_client text NOT NULL
);
CREATE INDEX IF NOT EXISTS realtime_session_nonce_expiry
  ON public.realtime_session_nonce(expires_at,consumed_at);

CREATE TABLE IF NOT EXISTS public.realtime_session_request(
  tenant_id text NOT NULL,
  source_client text NOT NULL,
  idempotency_key text NOT NULL,
  request_hash text NOT NULL,
  response_json text NOT NULL,
  created_at double precision NOT NULL,
  PRIMARY KEY(tenant_id,source_client,idempotency_key)
);

CREATE TABLE IF NOT EXISTS public.automation_executions(
  tenant_id text NOT NULL,
  event_id text NOT NULL,
  workflow_key text NOT NULL,
  request_hash text NOT NULL,
  status text NOT NULL CHECK(status IN ('RUNNING','ACTIONS_COMPLETED','COMPLETED','FAILED','RETRY_PENDING','DEAD_LETTER')),
  approved_actions text NOT NULL,
  correlation_id text NOT NULL,
  execution_id text,
  started_at text NOT NULL,
  completed_at text,
  updated_at text NOT NULL,
  PRIMARY KEY(tenant_id,event_id,workflow_key)
);
CREATE INDEX IF NOT EXISTS automation_executions_status
  ON public.automation_executions(tenant_id,status,updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS automation_executions_orchestrator
  ON public.automation_executions(execution_id)
  WHERE execution_id IS NOT NULL AND execution_id <> '';

CREATE TABLE IF NOT EXISTS public.automation_action_executions(
  tenant_id text NOT NULL,
  event_id text NOT NULL,
  workflow_key text NOT NULL,
  action text NOT NULL,
  request_hash text NOT NULL,
  status text NOT NULL CHECK(status IN ('COMPLETED')),
  receipt text NOT NULL,
  completed_at text NOT NULL,
  PRIMARY KEY(tenant_id,event_id,workflow_key,action),
  FOREIGN KEY(tenant_id,event_id,workflow_key)
    REFERENCES public.automation_executions(tenant_id,event_id,workflow_key)
);

COMMIT;
