# Consent and preferences

Preferences are keyed by tenant, contact, and channel (`sms` or `email`). Status is subscribed, unsubscribed, or suppressed with source, timestamps, and reason. Missing records deny marketing sends. Telnexa STOP events and Klyrow unsubscribe/complaint events update the centralized record. Tenant-scoped APIs cannot inspect or change another tenant's preferences. Transactional/legal exceptions require an explicit, audited policy outside workflow logic.

`GET|PUT /v1/customers/{id}/preferences` is canonical. Marketing never silently becomes transactional. Proof references, policy versions, regional rules, topics, and source evidence must be mapped from the approved consent authority before launch.
