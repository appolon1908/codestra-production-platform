def pre_init_hook(env):
    """Bridge installation over a pre-field core schema.

    The field remains owned by the core addon; this compatibility DDL makes
    the analytics view safe before the operator's subsequent core upgrade.
    """
    env.cr.execute(
        "ALTER TABLE codestra_crm_call_followup "
        "ADD COLUMN IF NOT EXISTS email_sent_at timestamp without time zone"
    )
    env.cr.execute(
        "CREATE INDEX IF NOT EXISTS codestra_crm_call_followup_email_sent_at_idx "
        "ON codestra_crm_call_followup (email_sent_at)"
    )
