# Production runbook

Status: `PREPARATION_ONLY`

Production cutover is prohibited. Before any cutover, require all ordered gates
to pass, capture a fresh quiesced database/filestore pair, verify digests and
restore, freeze code/images, neutralize communications in rehearsal, obtain all
owner decisions, confirm monitoring, define the maintenance window, and record
the exact separately required cutover authorization.

