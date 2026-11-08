import asyncio
import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

from app import app
from verifier import Store, object_json
from agent_bridge import discover_verifier, verify_via_agentverse, evaluate_query
from agent_protocol import AgentVerificationRequest, AgentVerificationResponse
from uagents import Model
from uagents_core.identity import Identity
from uagents_core.envelope import Envelope

ROOT = Path(__file__).parent
GOOD = 'def add(a, b):\n    return a + b'


class ExtensionServiceTests(unittest.TestCase):
    def setUp(self):
        for target in ('agent_bridge.urlopen', 'reviewer.urlopen', 'uagents.communication.send_sync_message'):
            guard = patch(target, side_effect=AssertionError('Unexpected live provider call in a unit test.'))
            guard.start()
            self.addCleanup(guard.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.identity = Identity.generate()
        self.sender = 'user1' + 'a' * 50
        self.env = {'CHATMATE_STATE_DIR': self.directory.name,
                    'CHATMATE_OPERATOR_TOKEN': 'o' * 32, 'CHATMATE_SUBMIT_TOKEN': 's' * 32,
                    'META_MODEL_API_KEY': 'private-meta-key', 'AGENTVERSE_API_KEY': 'private-agentverse-key',
                    'CHATMATE_AGENT_QUERY_TOKEN': 'q' * 32, 'CHATMATE_AGENT_ADDRESS': self.identity.address}
        self.patch_env = patch.dict(os.environ, self.env)
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)
        self.store = Store()
        self.suite = self.store.freeze(object_json((ROOT/'demo'/'contract.json').read_text(encoding='utf-8')))

    def envelope(self, request_id, *, source_hash=None, expires=None):
        report = self.store.verify(self.suite, GOOD)
        if source_hash:
            report['source_sha256'] = source_hash
        message = AgentVerificationResponse(decision=report['decision'], request_id=request_id, report_json=json.dumps(report))
        envelope = Envelope(version=1, sender=self.identity.address, target=self.sender, session=uuid4(),
            schema_digest=Model.build_schema_digest(AgentVerificationResponse), expires=expires or int(time.time())+60)
        envelope.encode_payload(message.model_dump_json())
        envelope.sign(self.identity)
        return envelope

    @patch('agent_bridge.urlopen')
    def test_agentverse_key_used_only_for_discovery(self, urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps({'agents': [{'address': self.identity.address, 'status': 'active'}]}).encode()
        urlopen.return_value.__enter__.return_value = response
        self.assertEqual(discover_verifier(), self.identity.address)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://agentverse.ai/v1/search/agents')
        self.assertEqual(request.get_header('Authorization'), 'Bearer private-agentverse-key')
        self.assertNotIn('private-meta-key', request.data.decode())
        response.read.return_value = b'{"agents":[{"address":"different-agent","status":"active"}]}'
        with self.assertRaises(ValueError):
            discover_verifier()

    def test_signed_response_binds_source_suite_nonce_and_sender(self):
        async def send(**kwargs):
            self.assertEqual(kwargs['message'].query_token, 'q'*32)
            return self.envelope(kwargs['message'].request_id)
        with patch('agent_bridge.discover_verifier', return_value=self.identity.address), \
             patch('uagents_core.identity.generate_user_address', return_value=self.sender), \
             patch('uagents.communication.send_sync_message', side_effect=send):
            result = asyncio.run(verify_via_agentverse(self.suite, GOOD))
        self.assertEqual(result['decision'], 'ACCEPT')
        self.assertTrue(result['agent_signature_verified'])
        self.assertNotIn('results', result)
        receipt = next((self.store.root/'agent-receipts').glob('*.json'))
        self.assertNotIn('private-agentverse-key', receipt.read_text())
        self.assertNotIn('q'*32, receipt.read_text())

    def test_wrong_nonce_source_expired_or_unsigned_reply_blocks(self):
        for attack in ('nonce', 'source', 'expired', 'signature'):
            async def send(**kwargs):
                envelope = self.envelope('0'*64 if attack == 'nonce' else kwargs['message'].request_id,
                    source_hash='0'*64 if attack == 'source' else None,
                    expires=int(time.time())-60 if attack == 'expired' else None)
                if attack == 'signature':
                    envelope.signature = None
                return envelope
            with self.subTest(attack=attack), patch('agent_bridge.discover_verifier', return_value=self.identity.address), \
                 patch('uagents_core.identity.generate_user_address', return_value=self.sender), \
                 patch('uagents.communication.send_sync_message', side_effect=send):
                with self.assertRaisesRegex(ValueError, 'blocked'):
                    asyncio.run(verify_via_agentverse(self.suite, GOOD))

    def test_remote_query_authentication_and_deterministic_result(self):
        message = AgentVerificationRequest(suite_id=self.suite, code=GOOD, request_id='b'*64, query_token='q'*32)
        result = evaluate_query(message)
        self.assertEqual(result.decision, 'ACCEPT')
        message.query_token = 'bad'
        with self.assertRaises(ValueError):
            evaluate_query(message)

    @patch('reviewer.urlopen')
    def test_meta_key_stays_on_server_and_review_never_grants_acceptance(self, urlopen):
        response = MagicMock()
        response.read.return_value = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'summary': 'Review complete', 'findings': [], 'suggested_tests': []})}}]}).encode()
        urlopen.return_value.__enter__.return_value = response
        client = app.test_client()
        result = client.post('/api/cross-review', json={'code': GOOD, 'language': 'python', 'question': 'Check boundaries'},
                             headers={'Authorization': 'Bearer ' + 's'*32})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['advisory'])
        self.assertNotIn('decision', result.json)
        self.assertEqual(result.json['source_sha256'], hashlib.sha256(GOOD.encode()).hexdigest())
        self.assertEqual(urlopen.call_args.args[0].get_header('Authorization'), 'Bearer private-meta-key')
        self.assertNotIn('private-meta-key', result.data.decode())
        self.assertEqual(client.post('/api/cross-review', json={'code': GOOD}).status_code, 403)

    @patch('agent_bridge.verify_via_agentverse', new_callable=AsyncMock)
    def test_gateway_endpoint_refuses_operator_and_cannot_accept_on_outage(self, query):
        query.side_effect = ValueError('Agent unavailable; blocked.')
        client = app.test_client()
        payload = {'suite_id': self.suite, 'code': GOOD}
        self.assertEqual(client.post('/api/verify-agent', json=payload,
            headers={'Authorization': 'Bearer ' + 'o'*32}).status_code, 403)
        result = client.post('/api/verify-agent', json=payload, headers={'Authorization': 'Bearer ' + 's'*32})
        self.assertEqual(result.json['decision'], 'BLOCK')


if __name__ == '__main__':
    unittest.main()
