# Final SMS/email gap-closure evidence — 2026-08-22

Live SMS and email delivery remained disabled throughout.

## n8n workflow inventory

The production database, rather than names alone, confirms active workflow IDs and successful execution rows:

| Function | Workflow ID | Deployed workflow | State |
|---|---|---|---|
| SMS delivery event | `CodestraCP21` | `CP-21-SMS.DELIVERED-V1` | active |
| SMS inbound | `CodestraCP20` | `CP-20-SMS.RECEIVED-V1` | active |
| SMS failure | `CodestraCP22` | `CP-22-SMS.FAILED-V1` | active |
| Email delivery | `CodestraCP24` | `CP-24-EMAIL.DELIVERED-V1` | active |
| Email bounce | `CodestraCP25` | `CP-25-EMAIL.BOUNCED-V1` | active |
| Email complaint | `CodestraCP26` | `CP-26-EMAIL.COMPLAINED-V1` | active |
| Email unsubscribe | `CodestraCP27` | `CP-27-EMAIL.UNSUBSCRIBED-V1` | active |
| Error/result handling | `CodestraCP90` | `CP-90-STANDARD-ERROR-V1` | active |
| Reconciliation | `N8W90Reconciliation20260722` | `N8-90 Reconciliation Monitor` | deployed; activation not certified |

The current control-plane worker dispatches queued messages directly in simulator/test mode. No distinct SMS or email n8n dispatch execution exists, so dispatch and result execution IDs cannot be certified yet.

## Captured event executions

Correlation `cert-8ac638935fe54ca29451aaacc877c377` was found inside retained n8n execution data:

- Email delivery event: execution `248`, workflow `CodestraCP24`, status `success`.
- SMS delivery event: execution `249`, workflow `CodestraCP21`, status `success`.
- A later replay-remediation SMS event: execution `252`, workflow `CodestraCP21`, status `success`.

Middleware delivery rows for the same correlation show n8n state `delivered`. Odoo initially dead-lettered both original events. A later SMS event converged to Odoo `delivered` after four attempts, proving retention and bounded recovery, but the authoritative Odoo database contains only a generic integration event for this correlation and no professional unified SMS/email timeline record.

## Remaining architectural defects

1. Runtime Kong still uses `key-auth` on the canonical communication route. The requested granular OAuth scopes are designed in `COMMUNICATION_OAUTH_SCOPE_MATRIX.csv` but not safely activated because an Odoo communications machine client and caller token rollout are absent.
2. Message creation does not enqueue an n8n dispatch event; the middleware worker directly consumes `queued` messages.
3. Odoo has immutable `codestra.email.delivery.status` evidence for delivered/bounced/deferred email and a generic integration event ledger, but no authoritative unified communication timeline/detail UI covering SMS and email.
4. Consequently, full Odoo-to-provider-to-Odoo correlation cannot yet be certified.

`FINAL_STATUS=FAIL`
