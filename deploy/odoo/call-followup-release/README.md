# Codestra Odoo 19 Call Follow-up Docker Release

This package builds the four reviewed call-follow-up addons into one
immutable Odoo image:

- `codestra_crm_call_followup`
- `codestra_crm_call_followup_api`
- `codestra_crm_call_followup_ux`
- `codestra_crm_call_followup_automation`

Source integration SHA: `b9b55274d726b2375f0a48ae30a2b1369c47e91c`.

Component heads:

- core: `3bf43b689da96eb1ab2444c30133a2dc43563be4`
- API: `985869b17ebd3211b87c48cf620bb34a011b910b`
- UX: `3bcca91f62a8e1ca67c9e4b850a72a9f317ed431`
- automation: `fde96222979e43f213f49eeee3d695bfdc862ddb`

## Safety defaults

- no `latest` image tag;
- deployment requires a `repository@sha256` image reference;
- automation remote delivery remains disabled in Odoo;
- install/upgrade runs as a one-shot container while the web service is
  stopped;
- production requires exact-SHA approval, staging evidence, backups, and a
  rollback rehearsal;
- the deploy script stops on migration or health failure and does not
  attempt an unsafe schema downgrade.

## Validate

```bash
deploy/odoo/call-followup-release/validate.sh
```

## Local build

```bash
PUSH=false deploy/odoo/call-followup-release/build.sh
```

A release push requires registry authentication:

```bash
PUSH=true \
  IMAGE_REPOSITORY=ghcr.io/appolon1908-hue/codestra-odoo-call-followup \
  deploy/odoo/call-followup-release/build.sh
```

Pushed builds produce SBOM and max-mode provenance attestations. Capture the
emitted immutable image reference.

## Deployment

Use `deploy.sh staging` first with an explicit staging Compose base. Use
`deploy.sh production` only after every gate in
`docs/CODEX_ODOO19_CALL_FOLLOWUP_DOCKER_RELEASE.md` passes.

Mounting the optional automation secrets does not activate remote delivery.
Activation of `codestra.call_followup_automation.enabled` is a separate,
approved, post-canary operation.
