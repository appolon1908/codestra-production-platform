# SMS integration

Telnexa is the sole SMS adapter. Destinations must be E.164, marketing requires positive SMS consent, suppression is checked, and segment count is metered. Sender authorization, quotas, quiet hours, country rules, wallet reservation, and final Telnexa charges remain mandatory production policy/provider gates.

`TELNEXA_MODE=simulator` returns synthetic accepted IDs without network traffic. Production additionally requires both global gates, a distinct credential, and private `10.40.0.2` endpoint. Provider events normalize into the ledger. `STOP` and `UNSUBSCRIBE` revoke consent and suppress SMS; `START` and `HELP` require an approved country/provider policy before automated effects.
