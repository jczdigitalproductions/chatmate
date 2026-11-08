"""Signed Fetch.ai request/reply adapter for other code-generating agents."""
import os
from pathlib import Path

from dotenv import load_dotenv
from uagents import Agent, Context, Model

from reviewer import review_async
from verifier import Store, public_report
import asyncio
from agent_protocol import AgentVerificationRequest, AgentVerificationResponse
from agent_bridge import evaluate_query

load_dotenv(Path(__file__).with_name(".env"))
seed = os.getenv("FETCH_AGENT_SEED")
allowed = {s.strip() for s in os.getenv("FETCH_ALLOWED_SENDERS", "").split(",") if s.strip()}
if not seed or (not allowed and len(os.getenv('CHATMATE_AGENT_QUERY_TOKEN', '')) < 32):
    raise RuntimeError("Set FETCH_AGENT_SEED plus FETCH_ALLOWED_SENDERS or CHATMATE_AGENT_QUERY_TOKEN.")


class ReviewRequest(Model):
    code: str
    language: str = "python"
    question: str = "Review correctness and security."


class ReviewResponse(Model):
    report_json: str


class VerificationRequest(Model):
    suite_id: str
    code: str


class VerificationResponse(Model):
    decision: str
    report_json: str


port = int(os.getenv("FETCH_PORT", "8001"))
agent = Agent(name="chatmate", seed=seed, port=port,
              endpoint=[os.getenv("FETCH_ENDPOINT", f"http://127.0.0.1:{port}/submit")])


@agent.on_message(model=ReviewRequest, replies={ReviewResponse})
async def handle_review(ctx: Context, sender: str, msg: ReviewRequest):
    import json
    if sender not in allowed:
        ctx.logger.warning("Rejected review from an unauthorized sender.")
        return
    try:
        report = await review_async({"code": msg.code, "language": msg.language, "question": msg.question})
    except ValueError as exc:
        report = {"error": str(exc)}
    await ctx.send(sender, ReviewResponse(report_json=json.dumps(report)))


@agent.on_message(model=VerificationRequest, replies={VerificationResponse})
async def handle_verification(ctx: Context, sender: str, msg: VerificationRequest):
    import json
    if sender not in allowed:
        ctx.logger.warning('Rejected verification from an unauthorized sender.')
        return
    try:
        report = await asyncio.to_thread(Store().verify, msg.suite_id, msg.code)
        report = public_report(report)
    except (ValueError, OSError, TypeError):
        report = {'decision': 'BLOCK', 'reasons': ['Required verification could not complete.']}
    await ctx.send(sender, VerificationResponse(decision=report['decision'], report_json=json.dumps(report)))


@agent.on_query(model=AgentVerificationRequest, replies={AgentVerificationResponse})
async def handle_gateway_query(ctx: Context, sender: str, msg: AgentVerificationRequest):
    try:
        reply = await asyncio.to_thread(evaluate_query, msg)
    except (ValueError, OSError, TypeError):
        ctx.logger.warning('Rejected or incomplete verifier query.')
        return
    await ctx.send(sender, reply)


if __name__ == "__main__":
    agent.run()
