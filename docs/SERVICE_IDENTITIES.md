# Service Identities

| Identity | Expected use | Local evidence | Result |
|---|---|---|---|
| `codestra-middleware-operator` | SSH maintenance to `10.40.0.1` | ED25519 fingerprint `SHA256:+IBJr4dwVz2NTJOD9nNJUvuOV/gJZpS6d/OoUyecYE4`; mode 0600 | BLOCKED: rejected for tested logical users |
| Odoo service | signed middleware ingress | environment names exist; positive credential unavailable | BLOCKED |
| n8n service | signed middleware ingress | environment names exist; positive credential unavailable | BLOCKED |
| Telnexa service | API and callback | simulator PASS; HMAC tests PASS | production BLOCKED |
| Klyrow service | API and callback | test adapter PASS; HMAC tests PASS | production BLOCKED |
| Kyqra service | jobs and result callback | safe job PASS; HMAC tests PASS | production BLOCKED |

No `/root/.ssh/config` aliases were present. No `kyqra-server`, `telnexa-server`, or `klyrow-server` target keys were discovered. Private key contents were not read or recorded.
