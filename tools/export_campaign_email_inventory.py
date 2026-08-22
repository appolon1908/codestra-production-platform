#!/usr/bin/env python3
"""Export the read-only Odoo campaign/email review matrix without credentials."""
from __future__ import annotations

import csv
import io
import subprocess
from pathlib import Path


QUERY = """
SELECT c.id,coalesce(m.vicidial_campaign_id,c.vicidial_campaign_reference,''),
       bu.code,c.name,c.code,
       (SELECT count(*) FROM call_center_campaign_agent_rel r
        JOIN res_users u ON u.id=r.res_users_id
        WHERE r.call_center_campaign_id=c.id AND u.active),
       c.active,m.id IS NOT NULL
FROM call_center_campaign c
JOIN call_center_business_unit bu ON bu.id=c.business_unit_id
LEFT JOIN call_center_campaign_mapping m ON m.campaign_id=c.id
ORDER BY bu.code,c.code,c.id
"""

EXPLICIT_REVIEW_PROPOSALS = {
    "COD": ("codestra.co", "codestra.agency"),
    "MBL": ("moneybeeloan.com", "moneybee.loan"),
}


def main() -> None:
    result = subprocess.run(
        ["docker", "exec", "-u", "postgres", "codestra-postgres-1", "psql",
         "-d", "codestra_odoo", "--csv", "-t", "-c", QUERY],
        check=True, capture_output=True, text=True,
    )
    rows = list(csv.reader(io.StringIO(result.stdout)))
    if len(rows) != 105:
        raise SystemExit(f"expected 105 campaigns, found {len(rows)}")
    output = Path("reports/campaign-email-provisioning/CAMPAIGN_EMAIL_MAPPING_REVIEW.csv")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([
            "ODOO_CAMPAIGN_ID", "VICIDIAL_CAMPAIGN_ID", "TENANT_ID", "CAMPAIGN_NAME",
            "CAMPAIGN_CODE", "ACTIVE_AGENT_COUNT", "PROPOSED_PRIMARY_DOMAIN",
            "ALIAS_DOMAINS", "MAPPING_STATUS",
        ])
        for odoo_id, vicidial_id, tenant, name, code, agents, active, mapped in rows:
            primary, aliases = EXPLICIT_REVIEW_PROPOSALS.get(tenant, ("", ""))
            if active != "t":
                status = "BLOCKED_INACTIVE_CAMPAIGN_REVIEW_REQUIRED"
            elif mapped != "t":
                status = "BLOCKED_EXACT_VICIDIAL_MAPPING_REQUIRED"
            else:
                status = "REVIEW_REQUIRED_NOT_ACTIVE"
            writer.writerow([odoo_id, vicidial_id, tenant, name, code, agents,
                             primary, aliases, status])
    print(f"CAMPAIGN_EMAIL_INVENTORY={len(rows)}")


if __name__ == "__main__":
    main()
