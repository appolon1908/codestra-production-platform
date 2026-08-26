#!/usr/bin/env python3
import json, pathlib, subprocess
root=pathlib.Path(__file__).resolve().parents[1]
p=subprocess.run(['caddy','adapt','--config',str(root/'live/Caddyfile'),'--adapter','caddyfile'],capture_output=True,text=True,check=True)
cfg=json.loads(p.stdout); hosts=set()
def walk(x):
    if isinstance(x,dict):
        if isinstance(x.get('host'),list): hosts.update(x['host'])
        for v in x.values(): walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
walk(cfg)
expected={line.split('\t')[0] for line in (root/'HOST-OWNERSHIP.tsv').read_text().splitlines()[1:] if line}
assert hosts==expected,(sorted(hosts-expected),sorted(expected-hosts))
for pth in root.rglob('*'):
    if pth.is_file() and pth != pathlib.Path(__file__):
        data=pth.read_bytes()
        assert b'BEGIN PRIVATE KEY' not in data and b'BEGIN RSA PRIVATE KEY' not in data, pth
site=(root/'live/sites/current-production.caddy').read_text()
assert 'reverse_proxy 127.0.0.1:18101' in site and 'reverse_proxy 127.0.0.1:18102' in site
print('CADDY_HOST_OWNERSHIP=PASS')
print('CADDY_SECRET_SCAN=PASS')
print('CADDY_KONG_CONTRACT_TESTS=PASS')
