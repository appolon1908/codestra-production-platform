from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from websocket_gateway.certification_latency import latency_summary, measure_delivery_batch, validate_load_scopes


@pytest.mark.parametrize('values', [[], [1, 2], [1] * 249, [True] * 250, [float('nan')] * 250, [float('inf')] * 250, [-1] * 250, ['1'] * 250])
def test_insufficient_or_invalid_samples_cannot_certify(values):
    with pytest.raises(ValueError):
        latency_summary(values)


def test_nearest_rank_p95_uses_all_measurements_and_exact_threshold():
    result = latency_summary([1] * 237 + [500] * 13)
    assert result['P95_DELIVERY_LATENCY'] == 'FAIL'
    assert result['P95_DELIVERY_LATENCY_MS'] == 500
    assert result['DELIVERY_SAMPLE_COUNT'] == 250
    assert latency_summary([1] * 238 + [900] * 12)['P95_DELIVERY_LATENCY'] == 'PASS'


def documents():
    return [dict(event_id=str(i), tenant_id='test', campaign_id='synthetic', agent_id=f'agent-{i}') for i in range(250)]


@pytest.mark.parametrize('bad', ['duplicate', 'missing', 'blank'])
def test_load_identity_uniqueness_and_complete_scope(bad):
    values = documents()
    if bad == 'duplicate':
        values[-1] = values[0]
    elif bad == 'missing':
        del values[-1]['agent_id']
    else:
        values[-1]['agent_id'] = ''
    with pytest.raises(ValueError):
        validate_load_scopes(values)


class Socket:
    def __init__(self, value):
        self.value = value

    async def recv(self):
        return json.dumps(self.value)


def test_every_measured_delivery_has_matching_stream_cursor_and_scope():
    values = documents()
    published = []
    async def publish(value):
        published.append(value)
        return int(value['event_id']) + 1
    sockets = [Socket({**doc, 'cursor': int(doc['event_id']) + 1}) for doc in values]
    result = asyncio.run(measure_delivery_batch(sockets, values, publish))
    assert len(result) == len(published) == 250
    assert latency_summary(result)['DELIVERY_SAMPLE_COUNT'] == 250


@pytest.mark.parametrize('field,value', [('cursor', 9999), ('cursor', True), ('tenant_id', 'other'), ('campaign_id', 'other'), ('agent_id', 'other'), ('event_id', 'other')])
def test_one_mismatched_delivery_rejects_entire_sample(field, value):
    values = documents()
    async def publish(value):
        return int(value['event_id']) + 1
    sockets = [Socket({**doc, 'cursor': int(doc['event_id']) + 1}) for doc in values]
    sockets[0].value[field] = value
    with pytest.raises(ValueError):
        asyncio.run(measure_delivery_batch(sockets, values, publish))


def test_timeout_does_not_drop_slow_sample():
    values = documents()
    async def publish(value):
        await asyncio.sleep(1)
        return 1
    with pytest.raises(TimeoutError):
        asyncio.run(measure_delivery_batch([Socket(doc) for doc in values], values, publish, timeout=0.001))


def test_certifier_load_path_is_jetstream_and_real_sample_summary():
    source = (Path(__file__).parents[1] / 'websocket_gateway/certify.py').read_text()
    load = source.split('load_identities = load_manifest[:250]', 1)[1]
    assert 'measure_delivery_batch(ordered_sockets, documents, publish_load)' in load
    assert 'publish_jetstream(document, jetstream)' in load
    assert 'latency_summary(samples)' in load
    assert 'await publish(' not in load
    assert 'max(latency_ms' not in source
    assert '**document["payload"]' not in source


def test_canonical_jetstream_payload_matches_calling_contract():
    import uuid
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
    from websocket_gateway.certification_latency import canonical_calling_envelope
    document = dict(event_id=str(uuid.uuid4()), call_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
                    type='agent.ready', tenant_id='synthetic', campaign_id='TEST_SYN', agent_id='TEST_AGENT',
                    business_unit_id='TEST', timestamp='2026-09-07T20:00:00Z', sequence=1,
                    payload={'event_id':'forged','tenant_id':'forged'})
    subject, envelope = canonical_calling_envelope(document)
    assert subject == 'telephony.agent.synthetic.TEST_SYN.TEST_AGENT'
    assert envelope['event']['event_id'] == document['event_id']
    assert envelope['event']['tenant_id'] == 'synthetic'
    source = yaml.safe_load((Path(__file__).parents[1] / 'contracts/telephony/codestra-calling-events.v1.asyncapi.yaml').read_text())
    Draft202012Validator({'$ref':'#/components/schemas/CallingEvent', 'components':source['components']}, format_checker=FormatChecker()).validate(envelope['event'])
    document['event_id'] = 'load-' + document['event_id']
    with pytest.raises(ValueError):
        canonical_calling_envelope(document)


@pytest.mark.parametrize("timeout", [0, -1, True, "1", float("inf"), float("nan")])
def test_invalid_delivery_timeout_rejected_before_any_publish(timeout):
    values = documents()
    async def forbidden(_document):
        pytest.fail("invalid timing policy must not publish")
    with pytest.raises(ValueError, match="timeout"):
        asyncio.run(measure_delivery_batch([Socket(doc) for doc in values], values, forbidden, timeout=timeout))


@pytest.mark.parametrize("business_unit", [None, False, 1, "", "x" * 129])
def test_canonical_business_unit_matches_schema_before_publish(business_unit):
    import uuid
    from websocket_gateway.certification_latency import canonical_calling_envelope
    document = dict(event_id=str(uuid.uuid4()), call_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
                    type="agent.ready", tenant_id="synthetic", campaign_id="TEST_SYN", agent_id="TEST_AGENT",
                    business_unit_id=business_unit, timestamp="2026-09-07T20:00:00Z", sequence=1, payload={})
    with pytest.raises(ValueError, match="business unit"):
        canonical_calling_envelope(document)
