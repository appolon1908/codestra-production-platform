# Agent states

The normalized state model is `LOGGED_OUT`, `LOGIN_PENDING`, `READY`,
`RINGING`, `INCALL`, `PAUSED`, `WRAP_UP`, `MANUAL_DIAL`, `CALLBACK`,
`TRANSFER`, `ERROR`, and `FORCED_LOGOUT`.

Every state event requires agent, tenant, workspace, campaign, previous/new
state, reason, aware timestamp, session and source. VICIdial remains the runtime
source for live state; middleware owns authorization and business history.

