"""Guard the unsigned Git preparation copy; these tests never contact a host.

The private completed package is separate. Passing these source tests is not
signature verification, runtime preflight, call execution or certification.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'VICIDIAL_ONE_CALL_PRODUCTION_AUTHORIZATION_PACKAGE.md'
RECEIPT = ROOT / 'reports/app-server-a/ONE_CALL_PREPARATION_20260904.json'


def fields() -> dict[str, str]:
    pairs = re.findall(r'^([A-Z][A-Z0-9_]*)=(.*)$', PACKAGE.read_text(), re.M)
    assert len(pairs) == len({key for key, _ in pairs}), 'Duplicate package field'
    return dict(pairs)


def test_original_fourteen_sections_retained_in_order():
    headings = re.findall(r'^## (\d+)\. (.+)$', PACKAGE.read_text(), re.M)
    assert [int(n) for n, _ in headings] == list(range(1, 17))
    assert headings[0][1] == 'Fixed system identity'
    assert headings[11][1] == 'Required named approvals'
    assert headings[13][1] == 'Final pre-call signoff'


@pytest.mark.parametrize('key', [
    'PILOT_CAMPAIGN_ID', 'PILOT_LIST_ID', 'APPROVED_OPERATOR_ID',
    'APPROVED_EXTENSION', 'DESTINATION_ALLOWLIST_E164',
    'APPROVED_CALLER_ID_DID', 'APPROVED_SIP_TRUNK_ID',
    'ACTIVATION_START_UTC', 'ACTIVATION_END_UTC', 'CONSENT_EVIDENCE_REFERENCE_FOR_DESTINATION',
    'PERMANENT_DNC_CHECK_REFERENCE', 'RECORDING_POLICY_ID_VERSION',
])
def test_unsupplied_pilot_values_are_not_invented_or_committed(key):
    assert fields()[key] == ''


@pytest.mark.parametrize('role', [
    'BUSINESS', 'COMPLIANCE_PRIVACY', 'SECURITY', 'OPERATIONS', 'TELEPHONY',
    'ODOO', 'N8N', 'RELEASE', 'ROLLBACK',
])
def test_each_approval_role_remains_explicit_and_unsigned(role):
    values = fields()
    assert values[f'{role}_APPROVER_NAME'] == ''
    assert values[f'{role}_APPROVAL_REFERENCE'] == ''
    assert values[f'{role}_APPROVAL_TIMESTAMP_UTC'] == ''


@pytest.mark.parametrize('key', [
    'PREDICTIVE_DIALING', 'AUTOMATED_DIALING', 'CUSTOMER_LISTS_PERMISSION',
    'CALLBACK_PERMISSION', 'TRANSFER_PERMISSION', 'SMS_PERMISSION', 'EMAIL_PERMISSION',
    'ROUTE_FALLBACK', 'N8N_CUSTOMER_COMMUNICATION',
])
def test_unrelated_effects_remain_denied_in_requested_scope(key):
    assert fields()[key] == 'DENIED'


def test_manual_call_is_single_attempt_and_no_retries():
    values = fields()
    assert values['DIAL_METHOD'] == 'MANUAL'
    for key in ('MAX_CALLS', 'MAX_CALL_ATTEMPTS', 'MAX_CONCURRENT_CALLS'):
        assert values[key] == '1'
    assert values['INITIAL_HOPPER'] == '0'
    assert values['RETRY_CALLS_AUTHORIZED'] == 'NO'
    assert 'A global flag alone does not enforce this scope' in PACKAGE.read_text()
    assert 'automatic expiry' in PACKAGE.read_text()


def test_unsigned_template_never_asserts_successful_observation_or_approval():
    values = fields()
    for key, value in values.items():
        assert value not in {'PASS', 'YES', 'VALIDATED', 'APPROVED', 'APPROVED_FOR_EXACTLY_ONE_MANUAL_CALL'}, key
    assert values['AUTHORIZATION_DECISION'] == 'BLOCKED'
    assert values['ALL_MANDATORY_FIELDS_COMPLETE'] == 'NO'
    assert values['ALL_REQUIRED_APPROVALS_VALID'] == 'NOT_VERIFIED'
    assert values['BUSINESS_FLOW_CERTIFIED'] == 'false'
    assert values['LIMITED_PRODUCTION_DECISION'] == 'NO_GO'
    assert values['PERSISTENT_PRODUCTION_ACTIVATION_AUTHORIZED'] == 'false'


def test_call_chain_and_side_effect_evidence_remain_unobserved():
    values = fields()
    for key in ('ASTERISK_UNIQUEID', 'ASTERISK_LINKEDID', 'VICIDIAL_CALL_ID',
                'MIDDLEWARE_CORRELATION_ID', 'MIDDLEWARE_EVENT_IDS', 'ODOO_CALL_RECORD_ID',
                'FINAL_DISPOSITION', 'RECORDING_POLICY_READBACK_REFERENCE'):
        assert values[key] == ''
    for key in ('PRE_CALL_BACKUP_GATE', 'PRE_CALL_ROLLBACK_GATE', 'CALL_EXECUTION_GATE',
                'CALL_CHAIN_RECONCILIATION_GATE', 'DUPLICATE_SIDE_EFFECT_CHECK',
                'UNRELATED_SIDE_EFFECT_CHECK', 'POST_CALL_FAIL_CLOSED_GATE'):
        assert values[key] == 'NOT_RUN'
    assert values['GLOBAL_CALL_ATTEMPTS'] == 'UNKNOWN'
    assert values['CALL_ATTEMPTS_BY_THIS_PREPARATION'] == '0'


def test_old_targets_are_history_not_current_approval():
    values = fields()
    assert values['SERVER_A_EXISTING_APPROVED_TARGET'] == ''
    assert values['SERVER_B_EXISTING_APPROVED_TARGET'] == ''
    assert values['CURRENT_EVENT_CHANGE_SCOPE'] == 'LIMITED_EVENT_CUTOVER_ONLY'
    assert values['QUARANTINED_EVENTS'] == 'NOT_OBSERVED'
    assert values['ARCHIVED_EVENTS'] == 'NOT_OBSERVED'
    assert values['ONE_CALL_CHANGE_ID'] == ''


def test_receipt_matches_package_without_claiming_runtime_execution():
    receipt = json.loads(RECEIPT.read_text())
    assert receipt['package_sha256'] == hashlib.sha256(PACKAGE.read_bytes()).hexdigest()
    assert receipt['basis'] == 'retrieval_and_source_preparation_only'
    assert receipt['package_state'] == 'DRAFT_BLOCKED'
    assert receipt['sentinel_connected_hosts'] == 0
    assert receipt['runtime_workflow_dispatched'] is False
    assert receipt['actual_server_package_modified'] is False
    assert receipt['call_attempts_by_this_preparation'] == 0
    assert receipt['global_call_attempts'] is None
    assert receipt['runtime_flags_observed'] is False
    assert receipt['business_flow_certified'] is False
    assert receipt['limited_production_decision'] == 'NO_GO'
    assert receipt['persistent_production_activation_authorized'] is False
    assert receipt['step_results']['1_authorization'] == 'INCOMPLETE_BLOCKED'
    assert set(list(receipt['step_results'].values())[1:]) == {'NOT_RUN'}
