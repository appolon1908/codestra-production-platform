BEGIN;

-- Older governed installations used text canonical IDs; new installations use
-- uuid.  Bind each foreign-key column to the installed canonical type instead
-- of assuming one lineage and producing an invalid foreign key on the other.
DO $migration$
DECLARE
 campaign_id_type text;
 agent_id_type text;
BEGIN
 SELECT format_type(a.atttypid,a.atttypmod) INTO STRICT campaign_id_type
 FROM pg_attribute a
 WHERE a.attrelid='control_plane.campaign'::regclass AND a.attname='id' AND NOT a.attisdropped;
 SELECT format_type(a.atttypid,a.atttypmod) INTO STRICT agent_id_type
 FROM pg_attribute a
 WHERE a.attrelid='control_plane.agent'::regclass AND a.attname='id' AND NOT a.attisdropped;
 IF campaign_id_type NOT IN ('text','uuid') OR agent_id_type NOT IN ('text','uuid') THEN
   RAISE EXCEPTION 'unsupported canonical campaign/agent identifier type';
 END IF;

 EXECUTE format($ddl$
  CREATE TABLE IF NOT EXISTS control_plane.campaign_email_domain (
   id uuid PRIMARY KEY, tenant_id text NOT NULL,
   campaign_id %s NOT NULL REFERENCES control_plane.campaign(id),
   campaign_name text NOT NULL, primary_domain text NOT NULL,
   alias_domains jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(alias_domains)='array'),
   sender_domain_verified boolean NOT NULL DEFAULT false,
   inbound_domain_verified boolean NOT NULL DEFAULT false,
   sending_enabled boolean NOT NULL DEFAULT false,
   receiving_enabled boolean NOT NULL DEFAULT false,
   default_reply_to text, support_address text, billing_address text,
   status text NOT NULL CHECK(status IN ('UNVERIFIED','ACTIVE','SUSPENDED','REVOKED')),
   created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
   approved_by text, approved_at timestamptz,
   UNIQUE(tenant_id,campaign_id), UNIQUE(tenant_id,primary_domain)
  )$ddl$, campaign_id_type);

 EXECUTE format($ddl$
  CREATE TABLE IF NOT EXISTS control_plane.agent_mailbox (
   mailbox_id uuid PRIMARY KEY, tenant_id text NOT NULL,
   agent_id %s NOT NULL REFERENCES control_plane.agent(id),
   employee_id text, keycloak_user_id text, odoo_user_id text, vicidial_user_id text,
   campaign_id %s NOT NULL REFERENCES control_plane.campaign(id),
   campaign_name text NOT NULL, domain text NOT NULL, local_part text NOT NULL,
   primary_email text NOT NULL, display_name text NOT NULL,
   sending_enabled boolean NOT NULL DEFAULT false, receiving_enabled boolean NOT NULL DEFAULT false,
   mailbox_status text NOT NULL CHECK(mailbox_status IN
     ('PROVISIONING','ACTIVE','SUSPENDED','DEACTIVATED','PROVISIONING_FAILED')),
   quota integer NOT NULL CHECK(quota > 0), rate_limit integer NOT NULL CHECK(rate_limit > 0),
   created_at timestamptz NOT NULL DEFAULT now(), activated_at timestamptz,
   suspended_at timestamptz, deactivated_at timestamptz,
   last_send_at timestamptz, last_receive_at timestamptz,
   provisioning_correlation_id uuid NOT NULL, provisioning_error text,
   audit_version bigint NOT NULL DEFAULT 1 CHECK(audit_version > 0),
   previous_mailbox_id uuid REFERENCES control_plane.agent_mailbox(mailbox_id),
   UNIQUE(tenant_id,domain,local_part), UNIQUE(tenant_id,agent_id,campaign_id)
  )$ddl$, agent_id_type, campaign_id_type);
END
$migration$;

CREATE TABLE IF NOT EXISTS control_plane.mailbox_provisioning_event (
 event_id uuid PRIMARY KEY,
 tenant_id text NOT NULL,
 idempotency_key text NOT NULL,
 payload_hash text NOT NULL,
 mailbox_id uuid REFERENCES control_plane.agent_mailbox(mailbox_id),
 status text NOT NULL,
 correlation_id uuid NOT NULL,
 error_detail_safe text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,idempotency_key)
);

ALTER TABLE control_plane.campaign_email_domain ENABLE ROW LEVEL SECURITY;
ALTER TABLE control_plane.agent_mailbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE control_plane.mailbox_provisioning_event ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS campaign_email_domain_tenant ON control_plane.campaign_email_domain;
CREATE POLICY campaign_email_domain_tenant ON control_plane.campaign_email_domain
 USING (tenant_id=current_setting('app.tenant_id',true))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS agent_mailbox_tenant ON control_plane.agent_mailbox;
CREATE POLICY agent_mailbox_tenant ON control_plane.agent_mailbox
 USING (tenant_id=current_setting('app.tenant_id',true))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
DROP POLICY IF EXISTS mailbox_event_tenant ON control_plane.mailbox_provisioning_event;
CREATE POLICY mailbox_event_tenant ON control_plane.mailbox_provisioning_event
 USING (tenant_id=current_setting('app.tenant_id',true))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true));

ALTER TABLE control_plane.campaign_email_domain OWNER TO codestra_control_plane_owner;
ALTER TABLE control_plane.agent_mailbox OWNER TO codestra_control_plane_owner;
ALTER TABLE control_plane.mailbox_provisioning_event OWNER TO codestra_control_plane_owner;
GRANT SELECT,INSERT,UPDATE ON control_plane.campaign_email_domain,
 control_plane.agent_mailbox,control_plane.mailbox_provisioning_event
 TO codestra_control_plane_runtime;
REVOKE DELETE,TRUNCATE,REFERENCES,TRIGGER ON control_plane.campaign_email_domain,
 control_plane.agent_mailbox,control_plane.mailbox_provisioning_event
 FROM codestra_control_plane_runtime;

COMMIT;
