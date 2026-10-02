# codestra-production-platform — Architecture Charts

> Repository: `appolon1908/codestra-production-platform`  
> Baseline branch: `release/production-activation`  
> Repository-local visual architecture. Update these diagrams when implementation or authority changes.

## 1. System context
```mermaid
flowchart LR
 A["Release operators"] --> B["Production platform control plane"]
 B --> R["codestra-production-platform<br/>Historical/production platform integration authority"]
 R --> S["release/evidence/config state"]
 R --> D["Caddy/Kong/Middleware/Odoo/N8N"]
```

## 2. Internal component architecture
```mermaid
flowchart TB
 I["Entrypoint / UI / API / CLI"] --> P["Identity, policy, validation"]
 P --> C["Core domain / orchestration"]
 C --> S["State / configuration / persistence"]
 C --> A["Adapters / integrations"]
 A --> X["Approved dependencies"]
 C --> O["Metrics, logs, traces, audit"]
```

## 3. Critical flow
```mermaid
sequenceDiagram
 participant U as Caller
 participant B as codestra-production-platform
 participant P as Policy
 participant C as Core
 participant S as State
 participant X as Dependency
 U->>B: Request / event / action
 B->>P: Authenticate + validate
 P-->>B: Decision
 B->>C: Plan, certify, promote, read back and rollback
 C->>S: Read / persist
 C->>X: Bounded integration
 X-->>C: Result / readback
 C-->>U: Normalized response
```

## 4. Deployment and promotion
```mermaid
flowchart LR
 F["Feature branch"] --> T["Tests / validation"]
 T --> PR["Pull request + review"]
 PR --> CI["CI green"]
 CI --> ST["Staging / isolated verification"]
 ST --> EX["Exact-SHA certification"]
 EX --> G{"Production approval?"}
 G -- No --> ST
 G -- Yes --> P["Production promotion"]
 P --> H["Health/readiness + rollback check"]
```

## 5. Observability and recovery
```mermaid
flowchart LR
 R["codestra-production-platform"] --> M["Metrics"]
 R --> L["Logs / audit"]
 R --> T["Traces / correlation"]
 M --> O["Observability stack"]
 L --> O
 T --> O
 O --> A["Dashboards / alerts"]
 R --> B["Backup / config snapshot"]
 B --> RR["Restore / rollback rehearsal"]
```

## Ownership notes
- **Role:** Historical/production platform integration authority
- **Primary boundary:** Production platform control plane
- **State/config:** release/evidence/config state
- **Dependencies/consumers:** Caddy/Kong/Middleware/Odoo/N8N
- Cross-repository effects must use reviewed contracts; production effects remain separately gated.
