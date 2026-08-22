PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mail_domain (
  id TEXT PRIMARY KEY,
  domain TEXT NOT NULL COLLATE NOCASE UNIQUE,
  business_unit_id TEXT,
  campaign_id TEXT,
  brand TEXT NOT NULL,
  domain_type TEXT NOT NULL CHECK (domain_type IN ('AGENT_CAMPAIGN','SHARED_INBOX','CORPORATE_ADMIN','SYSTEM_TRANSACTIONAL','SERVICE_ONLY')),
  active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0,1)),
  allow_agent_send INTEGER NOT NULL DEFAULT 0 CHECK (allow_agent_send IN (0,1)),
  allow_agent_receive INTEGER NOT NULL DEFAULT 0 CHECK (allow_agent_receive IN (0,1)),
  allow_standalone_users INTEGER NOT NULL DEFAULT 0 CHECK (allow_standalone_users IN (0,1)),
  allow_shared_mailboxes INTEGER NOT NULL DEFAULT 0 CHECK (allow_shared_mailboxes IN (0,1)),
  admin_override_allowed INTEGER NOT NULL DEFAULT 0 CHECK (admin_override_allowed IN (0,1)),
  mailbox_backend TEXT NOT NULL DEFAULT 'stalwart',
  mx_status TEXT NOT NULL DEFAULT 'UNKNOWN', spf_status TEXT NOT NULL DEFAULT 'UNKNOWN',
  dkim_status TEXT NOT NULL DEFAULT 'UNKNOWN', dmarc_status TEXT NOT NULL DEFAULT 'UNKNOWN',
  mta_sts_status TEXT NOT NULL DEFAULT 'UNKNOWN', tls_rpt_status TEXT NOT NULL DEFAULT 'UNKNOWN',
  default_from_name TEXT, default_from_address TEXT,
  assignment_status TEXT NOT NULL CHECK (assignment_status IN ('ASSIGNED','SYSTEM_ONLY','BLOCKED_MISSING_CAMPAIGN_ASSIGNMENT')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_verified_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS mail_domain_campaign_authority
  ON mail_domain(domain, campaign_id) WHERE campaign_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS mail_user (
  mail_user_uuid TEXT PRIMARY KEY,
  keycloak_subject TEXT NOT NULL UNIQUE,
  odoo_user_id INTEGER UNIQUE,
  display_name TEXT NOT NULL,
  primary_address TEXT NOT NULL COLLATE NOCASE UNIQUE,
  domain_id TEXT NOT NULL REFERENCES mail_domain(id) ON DELETE RESTRICT,
  campaign_id TEXT,
  business_unit_id TEXT,
  user_type TEXT NOT NULL CHECK (user_type IN ('ODOO_LINKED','STANDALONE','SHARED_INBOX_MEMBER','ADMIN')),
  role TEXT NOT NULL CHECK (role IN ('EMAIL_OWNER','EMAIL_ADMIN','DOMAIN_ADMIN','CAMPAIGN_MANAGER','SUPERVISOR','AGENT','STANDALONE_MAIL_USER','SHARED_INBOX_USER','READ_ONLY_AUDITOR','SERVICE_ACCOUNT')),
  quota INTEGER NOT NULL CHECK (quota > 0), active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  mfa_required INTEGER NOT NULL DEFAULT 1 CHECK (mfa_required IN (0,1)),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login TEXT,
  CHECK ((user_type = 'ODOO_LINKED' AND odoo_user_id IS NOT NULL) OR user_type <> 'ODOO_LINKED')
);

CREATE TABLE IF NOT EXISTS mail_alias (
  id TEXT PRIMARY KEY, address TEXT NOT NULL COLLATE NOCASE UNIQUE,
  domain_id TEXT NOT NULL REFERENCES mail_domain(id) ON DELETE RESTRICT,
  target_mail_user_uuid TEXT NOT NULL REFERENCES mail_user(mail_user_uuid) ON DELETE RESTRICT,
  campaign_id TEXT, active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)), created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shared_mailbox (
  mailbox_uuid TEXT PRIMARY KEY, address TEXT NOT NULL COLLATE NOCASE UNIQUE,
  domain_id TEXT NOT NULL REFERENCES mail_domain(id) ON DELETE RESTRICT,
  campaign_id TEXT NOT NULL, supervisor_mail_user_uuid TEXT REFERENCES mail_user(mail_user_uuid),
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shared_mailbox_member (
  mailbox_uuid TEXT NOT NULL REFERENCES shared_mailbox(mailbox_uuid) ON DELETE CASCADE,
  mail_user_uuid TEXT NOT NULL REFERENCES mail_user(mail_user_uuid) ON DELETE CASCADE,
  permission TEXT NOT NULL CHECK (permission IN ('READ','SEND','MANAGE')),
  PRIMARY KEY(mailbox_uuid, mail_user_uuid)
);

CREATE TABLE IF NOT EXISTS mail_message (
  message_uuid TEXT PRIMARY KEY, mailbox_uuid TEXT, tenant TEXT NOT NULL,
  campaign TEXT, domain TEXT NOT NULL, channel TEXT NOT NULL DEFAULT 'EMAIL' CHECK(channel='EMAIL'),
  direction TEXT NOT NULL CHECK(direction IN ('INBOUND','OUTBOUND')),
  sender TEXT NOT NULL, recipients_json TEXT NOT NULL, thread_uuid TEXT NOT NULL,
  message_id_header TEXT, in_reply_to TEXT, references_json TEXT NOT NULL DEFAULT '[]',
  provider_message_id TEXT, mailbox_message_id TEXT, desired_state TEXT NOT NULL,
  actual_state TEXT NOT NULL, correlation_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(tenant,idempotency_key), UNIQUE(mailbox_message_id), UNIQUE(provider_message_id)
);

CREATE TABLE IF NOT EXISTS mail_audit (
  audit_uuid TEXT PRIMARY KEY, actor_subject TEXT NOT NULL, action TEXT NOT NULL,
  domain_id TEXT, campaign_id TEXT, reason TEXT, message_uuid TEXT,
  outcome TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_run (
  run_uuid TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
  status TEXT NOT NULL, findings_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS mail_app_password (
  credential_uuid TEXT PRIMARY KEY,
  mail_user_uuid TEXT NOT NULL REFERENCES mail_user(mail_user_uuid) ON DELETE CASCADE,
  label TEXT NOT NULL, secret_salt TEXT NOT NULL, secret_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  created_at TEXT NOT NULL, rotated_at TEXT, revoked_at TEXT,
  UNIQUE(mail_user_uuid,label)
);
