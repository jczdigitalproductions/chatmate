"""Local Chatmate UI and JSON endpoint."""
from pathlib import Path
import hmac
import os
import asyncio
import hashlib

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from reviewer import review, meta_review, validate, ReviewError
from verifier import Store, generate_cases, public_report, object_json

load_dotenv(Path(__file__).with_name(".env"))
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 256_000


def authorized(role):
    operator = os.getenv('CHATMATE_OPERATOR_TOKEN', '')
    submit = os.getenv('CHATMATE_SUBMIT_TOKEN', '')
    expected = operator if role == 'operator' else submit
    return (len(operator) >= 32 and len(submit) >= 32 and operator != submit
            and hmac.compare_digest(request.headers.get('Authorization', '').encode(), f'Bearer {expected}'.encode()))


@app.post('/api/suites/draft')
def draft_suite():
    if not authorized('operator'):
        return jsonify(error='A separate operator credential is required.'), 403
    payload = request.get_json()
    try:
        if not isinstance(payload, dict) or set(payload) != {'requirements', 'function', 'parameters'}:
            raise ValueError('Send only requirements, function and parameters; no candidate source.')
        return jsonify(generate_cases(**payload))
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@app.post('/api/suites/freeze')
def freeze_suite():
    if not authorized('operator'):
        return jsonify(error='A separate operator credential is required.'), 403
    payload = request.get_json()
    try:
        if not isinstance(payload, dict) or set(payload) != {'contract', 'provenance'}:
            raise ValueError('Send the reviewed contract and its provenance.')
        return jsonify(suite_id=Store().freeze(payload['contract'], payload['provenance']))
    except (ValueError, TypeError, OSError) as exc:
        return jsonify(error=str(exc)), 400


@app.post('/api/suites/demo')
def demo_suite():
    if not authorized('operator'):
        return jsonify(error='A separate operator credential is required.'), 403
    contract = object_json((Path(__file__).parent / 'demo' / 'contract.json').read_text(encoding='utf-8'))
    return jsonify(suite_id=Store().freeze(contract), origin='Operator-authored offline fixture')


@app.post('/api/verify')
def verify_code():
    if not authorized('submit'):
        return jsonify(error='A separate submission credential is required.'), 403
    payload = request.get_json()
    try:
        if not isinstance(payload, dict) or set(payload) != {'suite_id', 'code'}:
            raise ValueError('Send only suite_id and code. Tests and policy are operator-owned.')
        return jsonify(public_report(Store().verify(payload['suite_id'], payload['code'])))
    except (ValueError, TypeError, OSError) as exc:
        return jsonify(error=str(exc), decision='BLOCK'), 400


@app.post('/api/verify-agent')
def verify_agent():
    if not authorized('submit'):
        return jsonify(error='A separate submission credential is required.'), 403
    payload = request.get_json()
    try:
        if not isinstance(payload, dict) or set(payload) != {'suite_id', 'code'}:
            raise ValueError('Send only suite_id and code.')
        from agent_bridge import verify_via_agentverse
        return jsonify(asyncio.run(verify_via_agentverse(payload['suite_id'], payload['code'])))
    except (ValueError, OSError, ImportError) as exc:
        return jsonify(decision='BLOCK', error=str(exc)), 400


@app.post('/api/cross-review')
def cross_review():
    if not authorized('submit'):
        return jsonify(error='A separate submission credential is required.'), 403
    payload = request.get_json()
    try:
        if not isinstance(payload, dict) or set(payload) - {'code', 'language', 'question'}:
            raise ValueError('Send code, language and an optional question.')
        code, language, question = validate(payload)
        result = meta_review(code, language, question)
        # Never promote model commentary into a deterministic gate decision.
        return jsonify(source_sha256=hashlib.sha256(code.encode()).hexdigest(), review=result,
                       advisory=True, provider='meta')
    except (ValueError, ReviewError) as exc:
        return jsonify(error=str(exc), advisory=True), 400


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/review")
def review_code():
    if not authorized('submit'):
        return jsonify(error='A separate submission credential is required.'), 403
    # Browser clients must use our origin; do not enable permissive CORS.
    if request.headers.get("Origin") not in (None, request.host_url.rstrip("/")):
        return jsonify(error="Cross-origin requests are not allowed."), 403
    payload = request.get_json()
    try:
        return jsonify(review(payload))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.after_request
def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
