"""Shared schema for the gateway's authenticated synchronous query protocol."""
from uagents import Model


class AgentVerificationRequest(Model):
    suite_id: str
    code: str
    request_id: str
    query_token: str


class AgentVerificationResponse(Model):
    decision: str
    request_id: str
    report_json: str
