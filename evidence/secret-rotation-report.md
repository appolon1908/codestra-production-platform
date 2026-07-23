# Secret rotation report

On 2026-07-23, five credential sets present in root-only raw container metadata
were rotated without recording their values. The first attempts failed safely:
rollback restored the prior stack after Redis secret ownership and then Odoo
direct-configuration consumption were diagnosed. Regression corrections now
preserve service-specific secret ownership and update both Odoo credential
stores atomically.

The successful run proved every old PostgreSQL role credential and the old
Redis credential invalid, then proved all affected service health. Unrelated
signing, encryption, VICIdial, SMTP, OAuth, provider, and webhook credentials
were not present in the artifacts and were not rotated.

Result: `PASS`

