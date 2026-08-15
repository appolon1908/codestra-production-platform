# Consent and preferences

Preferences are keyed by tenant, contact, and channel (`sms` or `email`). Status is subscribed, unsubscribed, or suppressed with source, timestamps, and reason. Missing records deny marketing sends. Telnexa STOP events and Klyrow unsubscribe/complaint events update the centralized record. Tenant-scoped APIs cannot inspect or change another tenant's preferences. Transactional/legal exceptions require an explicit, audited policy outside workflow logic.
