# Recordings

Policies are `ALWAYS`, `ON_ANSWER`, `ON_AGENT_CONNECT`, `MANUAL_APPROVED`, and
`DISABLED`, scoped by tenant, campaign, jurisdiction, notice/consent, retention
and access role.

Metadata includes recording/call/tenant/workspace/campaign/agent identifiers,
customer reference, start/end/duration, opaque storage reference, checksum,
format, channel count, retention/access class and transcript/middleware sync
state. Raw paths are never returned to clients. The lab recording test uses
only synthetic local echo audio.

