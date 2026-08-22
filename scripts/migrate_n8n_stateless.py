#!/usr/bin/env python3
"""Replace only governed validation nodes while preserving workflow activation."""
import json, sys

if len(sys.argv)!=4:
    raise SystemExit("usage: migrate_n8n_stateless.py CURRENT GENERATED OUTPUT")
current=json.load(open(sys.argv[1],encoding="utf-8"))
generated=json.load(open(sys.argv[2],encoding="utf-8"))
templates={item["id"]:item for item in generated}
changed=0
for workflow in current:
    template=templates.get(workflow.get("id"))
    if not template: continue
    replacement=next((node for node in template["nodes"] if node["name"]=="Validate, deduplicate and preserve context"),None)
    if replacement is None: continue
    nodes=workflow.get("nodes",[])
    index=next((i for i,node in enumerate(nodes) if node.get("name")==replacement["name"]),None)
    if index is None: raise SystemExit(f"validation node missing: {workflow['id']}")
    nodes[index]["parameters"]=replacement["parameters"]
    workflow["staticData"]=None
    changed+=1
if changed != len(templates)-1: # error workflow has no validation node
    raise SystemExit(f"expected {len(templates)-1} governed workflows, changed {changed}")
with open(sys.argv[3],"w",encoding="utf-8") as handle:
    json.dump(current,handle,indent=2)
print(f"changed={changed} active_preserved={sum(bool(x.get('active')) for x in current)}")
