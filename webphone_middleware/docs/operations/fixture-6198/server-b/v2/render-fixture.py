#!/usr/bin/env python3
import argparse, hashlib, json, os, pathlib, tempfile

def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

p=argparse.ArgumentParser()
p.add_argument("--secret-file",required=True)
p.add_argument("--output-dir",required=True)
a=p.parse_args()
os.umask(0o077)
secret_path=pathlib.Path(a.secret_file)
if not secret_path.is_file() or secret_path.is_symlink(): raise SystemExit("invalid secret reference")
secret=secret_path.read_bytes()
if not secret or any(x<0x20 or x==0x7f for x in secret): raise SystemExit("invalid secret")
try: secret=secret.decode("utf-8")
except UnicodeDecodeError: raise SystemExit("invalid secret encoding")
base=pathlib.Path(__file__).resolve().parent
out=pathlib.Path(a.output_dir)
if out.is_symlink() or (out.exists() and not out.is_dir()): raise SystemExit("unsafe output")
out.mkdir(mode=0o700,parents=True,exist_ok=True)
template=(base/"templates/pjsip-6198.conf.in").read_text()
if template.count("@SIP_SECRET@")!=1: raise SystemExit("template placeholder mismatch")
files={
 "pjsip-6198.conf":template.replace("@SIP_SECRET@",secret),
 "extensions-6198.conf":(base/"templates/extensions-6198.conf").read_text(),
}
for name,data in files.items():
    target=out/name
    if target.is_symlink() or (target.exists() and not target.is_file()): raise SystemExit("unsafe target")
    fd,tmp=tempfile.mkstemp(prefix="."+name+".",dir=out,text=True)
    try:
        with os.fdopen(fd,"w") as h: h.write(data); h.flush(); os.fsync(h.fileno())
        os.chmod(tmp,0o600); os.replace(tmp,target); fsync_dir(out)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
redacted=files["pjsip-6198.conf"].replace(secret,"<redacted>")
structure={"pjsip_sha256":hashlib.sha256(redacted.encode()).hexdigest(),
           "dialplan_sha256":hashlib.sha256(files["extensions-6198.conf"].encode()).hexdigest()}
(out/"redacted-structure.json").write_text(json.dumps(structure,sort_keys=True)+"\n")
print("render complete; secret redacted")
