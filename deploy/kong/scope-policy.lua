local path = kong.request.get_path()
local method = kong.request.get_method()
local claims = kong.ctx.shared.authenticated_jwt_token and kong.ctx.shared.authenticated_jwt_token.claims or {}
local scopes = {}
for value in string.gmatch(claims.scope or "", "%S+") do scopes[value] = true end
local required
if path:find("^/api/v1/results/messages/") then required = "communications.result.write"
elseif path:find("^/api/v1/control/messages/.+/dispatch$") then required = "communications.message.dispatch"
elseif path == "/api/v1/control/messages" then required = "communications.message.create"
elseif path:find("^/api/v1/messages/.+/events$") then required = "communications.message.events.read"
elseif path:find("^/api/v1/messages/") then required = "communications.message.read"
elseif path:find("^/api/v1/reconciliation/") and method == "POST" then required = "communications.reconciliation.execute"
elseif path:find("^/api/v1/reconciliation/") then required = "communications.reconciliation.read"
elseif path:find("^/api/v1/results/") then required = "sync.result.write"
elseif path:find("^/api/v1/control/campaigns") then required = method == "GET" and "mapping.read" or "campaign.write"
elseif path:find("^/api/v1/control/agents") then required = method == "GET" and "mapping.read" or "agent.write"
elseif path:find("^/api/v1/control/memberships") then required = method == "GET" and "mapping.read.minimum" or "sync.execute"
elseif path:find("^/api/v1/control/adapters") then required = "sync.execute" end
if required and not scopes[required] then return kong.response.exit(403,{error="insufficient_scope",required_scope=required}) end

local tenant = kong.request.get_header("X-Tenant-ID")
local authorized_tenant = claims.tenant_id or claims.tenant
if not authorized_tenant or authorized_tenant == "" then
  return kong.response.exit(403,{error="tenant_claim_required"})
end
if tenant and tenant ~= authorized_tenant then
  return kong.response.exit(403,{error="cross_tenant_denied"})
end
kong.service.request.set_header("X-Authenticated-Client", claims.azp or "unknown")
kong.service.request.set_header("X-Authenticated-Tenant", authorized_tenant)
local gateway_secret=os.getenv("KONG_CONTROL_PLANE_GATEWAY_SECRET")
if not gateway_secret or gateway_secret=="" then return kong.response.exit(503,{error="gateway_identity_unavailable"}) end
kong.service.request.set_header("X-Codestra-Gateway-Secret",gateway_secret)
