"""Agentverse discovery plus signed, pinned-address uAgents verification."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.request import Request, urlopen

from verifier import Store, object_json, public_report, POLICY


def discover_verifier():
    key = os.getenv('AGENTVERSE_API_KEY', '')
    address = os.getenv('CHATMATE_AGENT_ADDRESS', '')
    if not key or not re.fullmatch(r'agent1[0-9a-z]{20,100}', address):
        raise ValueError('Configure AGENTVERSE_API_KEY and a pinned CHATMATE_AGENT_ADDRESS on the gateway.')
    body = {'search_text': address, 'offset': 0, 'limit': 30,
            'sort': 'relevancy', 'direction': 'asc', 'filters': {'state': ['active']}}
    request = Request('https://agentverse.ai/v1/search/agents', data=json.dumps(body).encode(),
                      headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError()
        data = object_json(raw)
        if not any(a.get('address') == address and a.get('status') == 'active' for a in data['agents']):
            raise ValueError()
    except Exception:
        raise ValueError('The pinned verifier was not confirmed active by Agentverse; verification is blocked.') from None
    return address


async def verify_via_agentverse(suite_id, source):
    from uagents.communication import send_sync_message
    from uagents_core.envelope import Envelope
    from uagents_core.identity import generate_user_address
    from uagents import Model
    from agent_protocol import AgentVerificationRequest, AgentVerificationResponse

    if not isinstance(source, str) or not 1 <= len(source) <= 50000:
        raise ValueError('Source must contain 1–50000 characters.')
    if not isinstance(suite_id, str) or not re.fullmatch('[0-9a-f]{64}', suite_id):
        raise ValueError('Invalid suite ID.')
    token = os.getenv('CHATMATE_AGENT_QUERY_TOKEN', '')
    if len(token) < 32:
        raise ValueError('Configure a private CHATMATE_AGENT_QUERY_TOKEN on gateway and verifier agent.')
    address = discover_verifier()
    request_id = secrets.token_hex(32)
    sender = generate_user_address()
    try:
        response = await send_sync_message(destination=address, sender=sender,
            message=AgentVerificationRequest(suite_id=suite_id, code=source,
                request_id=request_id, query_token=token), timeout=45)
        if (not isinstance(response, Envelope) or response.sender != address or response.target != sender
                or response.schema_digest != Model.build_schema_digest(AgentVerificationResponse)
                or response.expires is None or response.expires < time.time() or not response.verify()):
            raise ValueError()
        payload = object_json(response.decode_payload())
        if payload['request_id'] != request_id:
            raise ValueError()
        report = object_json(payload['report_json'])
        if (report['decision'] not in ('ACCEPT', 'BLOCK') or payload['decision'] != report['decision']
                or report['suite_id'] != suite_id or report['source_sha256'] != hashlib.sha256(source.encode()).hexdigest()):
            raise ValueError()
        if report['decision'] == 'ACCEPT' and (type(report.get('total')) is not int or not 6 <= report['total'] <= 100
                or type(report.get('passed')) is not int or report['passed'] != report['total'] or report.get('policy') != POLICY):
            raise ValueError()
        # Retain the original signed envelope for operator-side audit.
        store = Store()
        audit = {'agent': address, 'request_id': request_id, 'envelope': response.model_dump(mode='json')}
        directory = store.root / 'agent-receipts'
        directory.mkdir(exist_ok=True)
        (directory / f'{request_id}.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
        return {**public_report(report), 'transport': 'agentverse', 'verifier_agent': address,
                'agent_signature_verified': True, 'agent_receipt_id': request_id}
    except Exception:
        raise ValueError('No valid, matching, signed verifier reply was received; verification is blocked.') from None


def evaluate_query(message):
    """Runs on the separate verifier host; queries cannot freeze suites."""
    from agent_protocol import AgentVerificationResponse
    token = os.getenv('CHATMATE_AGENT_QUERY_TOKEN', '')
    if (len(token) < 32 or not hmac.compare_digest(token.encode(), message.query_token.encode())
            or not re.fullmatch('[0-9a-f]{64}', message.request_id)):
        raise ValueError('Unauthorized verifier query.')
    report = public_report(Store().verify(message.suite_id, message.code))
    return AgentVerificationResponse(decision=report['decision'], request_id=message.request_id,
                                     report_json=json.dumps(report))
