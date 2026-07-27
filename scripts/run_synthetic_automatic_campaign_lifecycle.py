#!/usr/bin/env python3
"""Run one bounded staging-only automatic-campaign lifecycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from campaign_provisioning import (
    CampaignDesignRequest,
    CampaignDesignService,
    LifecycleStore,
    PrivateAdapterClient,
    PrivateAdapterConfig,
    SQLiteDesignRepository,
    run_synthetic_lifecycle,
)
from scripts.synthetic_automatic_campaign_gate import load_env, validate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    values = load_env(args.config)
    validate(values)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    request = CampaignDesignRequest(
        integration_uuid=values["INTEGRATION_UUID"],
        odoo_campaign_id=int(values["ODOO_CAMPAIGN_ID"]),
        business_unit="TEST",
        purpose="E2E",
        direction="outbound",
        environment="staging",
        default_language="en",
        time_zone="America/Santo_Domingo",
        calling_hours="STAGING-NO-DIAL",
        consent_policy="SYNTHETIC-NO-CONTACT",
        dnc_policy="GLOBAL-DNC-V1",
        recording_policy="STAGING-NO-RECORDING",
        lead_source_policy="SYNTHETIC-ONLY",
        callback_policy="DISABLED",
        appointment_policy="DISABLED",
        disposition_family="TEST-E2E-V1",
        script_template="TEST-E2E-AGENT-V1",
        n8n_template="TEST-E2E-INACTIVE-V1",
        reporting_category="SYNTHETIC-E2E",
        owner_user_id=int(values["OWNER_USER_ID"]),
        supervisor_user_id=int(values["SUPERVISOR_USER_ID"]),
        activation_policy="MANUAL-NOT-AUTHORIZED",
        agent_roles=("AGENT",),
        transfer_roles=("CLOSERS", "INBOUND"),
    )
    adapter = PrivateAdapterClient(
        PrivateAdapterConfig(
            base_url=values["ADAPTER_URL"],
            ca_file=values["ADAPTER_CA_FILE"],
            client_cert_file=values["ADAPTER_CLIENT_CERT_FILE"],
            client_key_file=values["ADAPTER_CLIENT_KEY_FILE"],
            hmac_file=values["ADAPTER_HMAC_FILE"],
        )
    )
    result = run_synthetic_lifecycle(
        CampaignDesignService(
            SQLiteDesignRepository(str(args.state_dir / "design.sqlite3"))
        ),
        LifecycleStore(str(args.state_dir / "lifecycle.sqlite3")),
        adapter,
        request,
        values["CORRELATION_ID"],
    )
    if result["list"]["list_id"] != int(values["VICIDIAL_LIST_ID"]):
        raise RuntimeError("allocated list did not match approved synthetic list")
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
