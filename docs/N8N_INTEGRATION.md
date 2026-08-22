# n8n integration

n8n consumes only middleware-normalized events and calls only middleware APIs. Workflow exports are cataloged in `n8n/control-plane/workflow-manifest.json`, inactive by default, and retain standardized errors and environment promotion. SMS receipt/delivery/failure/opt-out and email delivery/bounce/complaint/unsubscribe preserve tenant and correlation IDs. Direct public channel-to-n8n webhooks and direct provider/database access are prohibited.
