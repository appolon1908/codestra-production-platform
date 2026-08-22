# Billing and metering

Each message reserves tenant/channel/message/month usage. SMS units use 160/153 character segments or Unicode 70/67; email units are recipients. Estimated, final, and customer charges use integer minor units and currency, never floating point.

Telnexa remains authoritative for wallet, rate, reservation, and final charge. Middleware stores reconciliation data, not a competing balance. Klyrow supplies final SaaS usage through its approved billing integration. Production reconciliation and charging remain blocked pending provider contracts and credentials.
