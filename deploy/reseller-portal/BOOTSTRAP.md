# Reseller portal initial authority

The first organization and owner are created by a one-shot operator command,
not by a public HTTP endpoint. Run it only against an empty portal database,
with `DATABASE_URL`, `PORTAL_BOOTSTRAP_ORGANIZATION`,
`PORTAL_BOOTSTRAP_SUBJECT`, and `PORTAL_BOOTSTRAP_EMAIL` supplied through the
approved secret/runtime authority:

```sh
PORTAL_BOOTSTRAP_CONFIRMATION=BOOTSTRAP_EMPTY_RESELLER_AUTHORITY \
python -m reseller_portal.bootstrap
```

The database insert is create-only and fails if portal authority already
exists. The command does not enable SMS, email, advertising, or any other
external business effect.
