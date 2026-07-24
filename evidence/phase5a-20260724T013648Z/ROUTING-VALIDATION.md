# Routing validation

The production template has protected `url_file` slots for primary, secondary, and recovery receivers. Only alerts matching both `severity="critical"` and `environment="production"` can enter those routes. The default route uses a separately protected fail-closed rejected-route audit receiver; the production template contains no test-only receiver.

Tests reject a staging alert targeting a production route and a production alert targeting a test-only route. Protected routes reject inline URLs. The installer rejects empty receiver files, `.invalid`, example, localhost, placeholder values, missing owner records, missing escalation policy/timing, and missing monitoring approval.

External routing remains blocked and undeployed.
