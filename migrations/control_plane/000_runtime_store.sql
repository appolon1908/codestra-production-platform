BEGIN;

CREATE TABLE IF NOT EXISTS public.events(
  event_id text PRIMARY KEY, tenant_id text NOT NULL, source text NOT NULL,
  event_type text NOT NULL, idempotency_key text NOT NULL, correlation_id text NOT NULL,
  envelope text NOT NULL, state text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
  next_attempt double precision NOT NULL DEFAULT 0, last_error text,
  created_at double precision NOT NULL, UNIQUE(tenant_id,source,idempotency_key));
CREATE INDEX IF NOT EXISTS events_state_due ON public.events(state,next_attempt);
CREATE INDEX IF NOT EXISTS events_correlation ON public.events(correlation_id);
CREATE TABLE IF NOT EXISTS public.event_deliveries(
  event_id text NOT NULL REFERENCES public.events(event_id), target text NOT NULL,
  state text NOT NULL DEFAULT 'queued', attempts integer NOT NULL DEFAULT 0,
  next_attempt double precision NOT NULL DEFAULT 0, last_error text,
  PRIMARY KEY(event_id,target));
CREATE TABLE IF NOT EXISTS public.preferences(
  tenant_id text NOT NULL, contact_id text NOT NULL, channel text NOT NULL,
  status text NOT NULL, source text NOT NULL, consent_at text, opted_out_at text,
  reason text, updated_at text NOT NULL, PRIMARY KEY(tenant_id,contact_id,channel));
CREATE TABLE IF NOT EXISTS public.integrations(
  name text PRIMARY KEY, paused integer NOT NULL DEFAULT 0, changed_at text NOT NULL);
CREATE TABLE IF NOT EXISTS public.circuits(
  name text PRIMARY KEY, state text NOT NULL DEFAULT 'closed', failures integer NOT NULL DEFAULT 0,
  opened_at double precision);
CREATE TABLE IF NOT EXISTS public.audit(
  id text PRIMARY KEY, actor text NOT NULL, role text NOT NULL, action text NOT NULL,
  object_type text NOT NULL, object_id text NOT NULL, tenant_id text, correlation_id text,
  metadata text NOT NULL, created_at text NOT NULL);
CREATE TABLE IF NOT EXISTS public.contacts(
  tenant_id text NOT NULL, customer_id text NOT NULL, odoo_partner_id text,
  phones text NOT NULL DEFAULT '[]', emails text NOT NULL DEFAULT '[]',
  identities text NOT NULL DEFAULT '{}', updated_at text NOT NULL,
  PRIMARY KEY(tenant_id,customer_id));
CREATE TABLE IF NOT EXISTS public.messages(
  message_id text PRIMARY KEY, channel text NOT NULL, tenant_id text NOT NULL,
  customer_id text NOT NULL, external_reference text, correlation_id text NOT NULL,
  request_id text NOT NULL, idempotency_key text NOT NULL, direction text NOT NULL,
  source_application text NOT NULL, campaign_id text, workflow_id text, sender text NOT NULL,
  recipient text NOT NULL, normalized_destination text NOT NULL, classification text NOT NULL,
  content_metadata text NOT NULL, content_payload text NOT NULL, provider text NOT NULL,
  downstream_provider text, status text NOT NULL, raw_provider_status text,
  estimated_cost_minor integer NOT NULL DEFAULT 0, final_cost_minor integer,
  customer_charge_minor integer, currency text NOT NULL, provider_message_id text,
  provider_error_code text, retry_count integer NOT NULL DEFAULT 0,
  provider_attempt integer NOT NULL DEFAULT 0, created_at text NOT NULL,
  submitted_at text, accepted_at text, sent_at text, delivered_at text, failed_at text,
  UNIQUE(tenant_id,idempotency_key));
CREATE INDEX IF NOT EXISTS messages_tenant_created ON public.messages(tenant_id,created_at);
CREATE INDEX IF NOT EXISTS messages_correlation ON public.messages(correlation_id);
CREATE TABLE IF NOT EXISTS public.message_events(
  event_id text PRIMARY KEY, message_id text NOT NULL REFERENCES public.messages(message_id),
  tenant_id text NOT NULL, event_type text NOT NULL, normalized_status text NOT NULL,
  raw_status text, envelope text NOT NULL, created_at text NOT NULL,
  UNIQUE(tenant_id,event_id));
CREATE TABLE IF NOT EXISTS public.suppressions(
  tenant_id text NOT NULL, channel text NOT NULL, destination text NOT NULL, kind text NOT NULL,
  reason text NOT NULL, source text NOT NULL, active integer NOT NULL DEFAULT 1,
  soft_bounce_count integer NOT NULL DEFAULT 0, updated_at text NOT NULL,
  PRIMARY KEY(tenant_id,channel,destination,kind));
CREATE TABLE IF NOT EXISTS public.usage_meter(
  id text PRIMARY KEY, message_id text NOT NULL, tenant_id text NOT NULL, channel text NOT NULL,
  units integer NOT NULL, estimated_cost_minor integer NOT NULL, final_cost_minor integer,
  customer_charge_minor integer, currency text NOT NULL, status text NOT NULL,
  billing_period text NOT NULL, created_at text NOT NULL, UNIQUE(message_id,status));
CREATE TABLE IF NOT EXISTS public.crawler_jobs(
  job_id text PRIMARY KEY, tenant_id text NOT NULL, correlation_id text NOT NULL,
  idempotency_key text NOT NULL, target_url text NOT NULL, status text NOT NULL,
  provider_job_id text, created_at text NOT NULL, UNIQUE(tenant_id,idempotency_key));
CREATE TABLE IF NOT EXISTS public.crawler_results(
  job_id text NOT NULL, result_key text NOT NULL, payload text NOT NULL,
  created_at text NOT NULL, PRIMARY KEY(job_id,result_key));
CREATE TABLE IF NOT EXISTS public.crm_customers(
  customer_id text PRIMARY KEY, kong_consumer_id text NOT NULL UNIQUE,
  kong_custom_id text NOT NULL UNIQUE, enabled integer NOT NULL DEFAULT 0,
  company_label text NOT NULL, business_unit_label text NOT NULL, created_at text NOT NULL);
CREATE TABLE IF NOT EXISTS public.crm_objects(
  customer_id text NOT NULL REFERENCES public.crm_customers(customer_id), external_id text NOT NULL,
  middleware_id text NOT NULL UNIQUE, odoo_model text NOT NULL, odoo_record_ref text,
  created_at text NOT NULL, updated_at text NOT NULL, PRIMARY KEY(customer_id,external_id));
CREATE TABLE IF NOT EXISTS public.crm_idempotency(
  customer_id text NOT NULL, operation text NOT NULL, idempotency_key text NOT NULL,
  request_hash text NOT NULL, response_json text NOT NULL, status_code integer NOT NULL,
  created_at text NOT NULL, PRIMARY KEY(customer_id,operation,idempotency_key));
CREATE TABLE IF NOT EXISTS public.crm_audit(
  id text PRIMARY KEY, customer_id text, action text NOT NULL, external_id text,
  permitted_fields text NOT NULL, result text NOT NULL, http_status integer NOT NULL,
  correlation_id text NOT NULL, created_at text NOT NULL);

COMMIT;
