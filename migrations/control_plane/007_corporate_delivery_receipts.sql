BEGIN;
CREATE TABLE IF NOT EXISTS public.automation_execution_attempts(
 execution_id text PRIMARY KEY,tenant_id text NOT NULL,event_id text NOT NULL,
 workflow_key text NOT NULL,request_hash text NOT NULL,started_at text NOT NULL,
 status text NOT NULL DEFAULT 'RUNNING' CHECK(status IN ('RUNNING','ACTIONS_COMPLETED','COMPLETED','FAILED','RETRY_PENDING','DEAD_LETTER')),
 completed_at text,
 FOREIGN KEY(tenant_id,event_id,workflow_key)
 REFERENCES public.automation_executions(tenant_id,event_id,workflow_key));
INSERT INTO public.automation_execution_attempts(
 execution_id,tenant_id,event_id,workflow_key,request_hash,started_at,status,completed_at)
 SELECT execution_id,tenant_id,event_id,workflow_key,request_hash,started_at,status,completed_at
 FROM public.automation_executions WHERE execution_id IS NOT NULL AND execution_id <> ''
 ON CONFLICT DO NOTHING;
CREATE INDEX IF NOT EXISTS automation_execution_attempts_operation
 ON public.automation_execution_attempts(tenant_id,event_id,workflow_key,status);
CREATE TABLE IF NOT EXISTS public.calling_ingress_receipts(
 tenant_id text NOT NULL,event_id text NOT NULL,idempotency_key text NOT NULL,
 body_sha256 text NOT NULL,certificate_sha256 text NOT NULL,receipt text NOT NULL,
 PRIMARY KEY(tenant_id,event_id,idempotency_key),UNIQUE(tenant_id,idempotency_key));
GRANT SELECT, INSERT, UPDATE ON public.automation_execution_attempts TO codestra_control_plane_runtime;
GRANT SELECT, INSERT ON public.calling_ingress_receipts TO codestra_control_plane_runtime;
REVOKE DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.automation_execution_attempts,
 public.calling_ingress_receipts FROM codestra_control_plane_runtime;
COMMIT;
