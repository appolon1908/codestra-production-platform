"""Create or remove short-lived synthetic users for staging HTTP login checks."""
import os

prefix = "synthetic-vertical-acceptance-"
existing = env["res.users"].sudo().search([("login", "like", prefix + "%")])
existing.unlink()
if os.environ.get("ACCEPTANCE_ACTION") == "create":
    password = os.environ["ACCEPTANCE_PASSWORD"]
    for suffix, group_xmlid in (
        ("admin", "base.group_system"),
        ("internal", "base.group_user"),
    ):
        group = env.ref(group_xmlid)
        env["res.users"].sudo().create({
            "name": f"SYNTHETIC Vertical Acceptance {suffix}",
            "login": prefix + suffix,
            "password": password,
            "group_ids": [(6, 0, group.ids)],
            "active": True,
        })
env.cr.commit()
print("PASS|temporary_acceptance_users_" + os.environ.get("ACCEPTANCE_ACTION", "removed"))
