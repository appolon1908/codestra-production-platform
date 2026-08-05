# Campaign governance

Campaign definitions carry tenant, workspace, business unit, type, dial
method, sources/lists, statuses, dispositions, callback and recording policy,
script, allowlisted transfers, business hours, timezone, line/drop/compliance
limits and active state. Supported types are inbound, manual, preview,
progressive, predictive, blended, callback and internal test.

Creation starts disabled. The adapter rejects unrestricted user groups,
preflights collisions before mutation, forces campaign/list/group/script state
to inactive, and never enables production dialing. Existing campaigns are not
reclassified by this mission.

