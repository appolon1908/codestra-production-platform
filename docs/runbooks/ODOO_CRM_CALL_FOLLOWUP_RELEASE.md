# Odoo CRM call follow-up release and rollback

This procedure releases `codestra_crm_call_followup` without modifying a live
checkout. The release directory must be materialized from the exact independently
reviewed Git commit and must contain only
`odoo_addons/codestra_crm_call_followup` from that commit.

## Safety gates

- Record the exact feature or merged SHA and confirm GitHub checks and independent
  approval apply to it.
- Keep `SEND_EVENTS`, `PRODUCTION_CALLBACKS_ENABLED`, `VICIDIAL_WRITES_ENABLED`,
  `EXTERNAL_DIAL_ENABLED`, `TRANSFERS_ENABLED`, `ENABLE_EXTERNAL_DELIVERY`,
  `ALLOW_LIVE_CALLS`, `ALLOW_LIVE_EMAIL`, `ALLOW_LIVE_SMS`, and
  `ALLOW_CAMPAIGN_ACTIVATION` false.
- Verify a paired PostgreSQL and filestore backup before upgrading the module.
- Never write directly to VICIdial, PBX, DIDWW, Twilio, carrier, Postal, or Odoo
  database tables. Completed-call canaries enter through middleware and authenticated
  Odoo RPC.

## Materialize the immutable addon

Create a root-owned release directory outside every live checkout. Export the addon
from the reviewed commit with `git archive`, verify the exported file hashes against
that commit, make the tree read-only, and set:

```text
ODOO_CRM_CALL_FOLLOWUP_ADDON_RELEASE=/opt/codestra/releases/odoo-crm-call-followup/<reviewed-sha>/odoo_addons
```

The staging and production Compose overlays require this value and mount only the
addon directory read-only. A branch name, mutable symlink, or dirty checkout is not
an acceptable value.

## Staging

Use the module-staging Compose authority plus
`deploy/odoo/compose.crm-call-followup.staging.yaml`. Capture a paired staging
database/filestore backup, validate the rendered Compose configuration, recreate
only staging Odoo, run the module upgrade with `--stop-after-init`, and restore the
normal staging container. Cron and all live-delivery flags remain disabled.

The staging database already contains `codestra_mail_inbox`. Set
`ODOO_CRM_CALL_FOLLOWUP_STAGING_MAIL_INBOX_RELEASE` to its exact reviewed release
directory. The overlay mounts that dependency read-only and fails closed when the
release authority is missing; do not accept registry warnings for an installed but
unavailable module.

The staging database currently contains `call_center_campaign 19.0.3.0.2`. Set
`ODOO_CALL_CENTER_ADDON_RELEASE` to the independently reviewed, immutable
`Codestra-SRL/codestra-odoo-addons` release whose manifest matches that installed
version. The overlay mounts only `call_center_campaign` over the older staging
checkout. Abort on a database/manifest version mismatch; never copy into or deploy
the dirty staging checkout.

Use synthetic `.invalid` identities. Validate queued recipients and retry state in
Odoo's mail models; do not deliver test messages to real customer addresses.

## Production

Use the approved production Compose stack plus
`deploy/odoo/compose.crm-call-followup.yaml`. Before recreation, capture a verified
paired production database/filestore backup and record the prior application SHA,
image digest, Compose list, module state, worker state, and restart counts. Upgrade
the module with `--stop-after-init`, then recreate only Odoo from the exact merged
release configuration.

## Rollback

Do not uninstall or downgrade the module in production. If any gate fails:

1. pause completed-call delivery in middleware while retaining events durably;
2. remove the canary users from the feature group;
3. stop Odoo workers;
4. restore the matching pre-change PostgreSQL and filestore pair;
5. restore the previous application SHA and exact prior Compose file list;
6. recreate only Odoo and verify web, registry, workers, cron, bus, mail, PostgreSQL,
   and middleware retention health;
7. leave retained events paused until the incident owner authorizes replay.

The exact rollback command is the environment's approved paired-restore workflow
documented in `operations/restore/ODOO_DATABASE_FILESTORE_RESTORE.md`, using the
captured pre-change `BACKUP_ID`. Never restore only the database or only the
filestore.
