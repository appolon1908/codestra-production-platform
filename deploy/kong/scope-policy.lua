local path = kong.request.get_path()
local method = kong.request.get_method()
local claims = kong.ctx.shared.authenticated_jwt_token and kong.ctx.shared.authenticated_jwt_token.claims or {}
local scopes = {}
for value in string.gmatch(claims.scope or "", "%S+") do scopes[value] = true end
local required
if path:find("^/api/v1/results/") then required = "sync.result.write"
elseif path:find("^/api/v1/reconciliation/") and method == "POST" then required = "reconciliation.execute"
elseif path:find("^/api/v1/reconciliation/") then required = "reconciliation.read"
elseif path:find("^/api/v1/control/campaigns") then required = method == "GET" and "mapping.read" or "campaign.write"
elseif path:find("^/api/v1/control/agents") then required = method == "GET" and "mapping.read" or "agent.write"
elseif path:find("^/api/v1/control/memberships") then required = method == "GET" and "mapping.read.minimum" or "sync.execute"
elseif path:find("^/api/v1/control/adapters") then required = "sync.execute" end
if required and not scopes[required] then return kong.response.exit(403,{error="insufficient_scope",required_scope=required}) end

local tenant = kong.request.get_header("X-Tenant-ID")
if tenant and claims.tenant and tenant ~= claims.tenant then
  return kong.response.exit(403,{error="cross_tenant_denied"})
end
kong.service.request.set_header("X-Authenticated-Client", claims.azp or "unknown")
kong.service.request.set_header("X-Authenticated-Tenant", claims.tenant or "")
