# Deployment

Deploy in section order from reviewed immutable commits. Capture zero active
calls/agents, run the encrypted platform backup, validate checksums, install
configuration, reload only the affected Asterisk module, and read back runtime
state. New campaigns/lists/users/phones/groups/scripts remain inactive.

Production campaign, bulk outbound, arbitrary number, autonomous calls and
messages, carrier and trunk feature flags must remain false. A live canary
requires a bounded signed authorization naming campaign, list, agent, phone,
destination hash, caller ID, operator, window, duration, recording policy and
rollback owner.

