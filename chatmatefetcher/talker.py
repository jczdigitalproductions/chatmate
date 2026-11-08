from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    chat_protocol_spec, ChatMessage, ChatAcknowledgement, TextContent,
)

TARGET = "<ASI:One Key>"

agent = Agent(
    name="laptop-talker",
    seed="laptop-talker-unique-seed-123",
    mailbox=True,  # registers a mailbox endpoint so the remote agent can reply to you
)

chat = Protocol(spec=chat_protocol_spec)

@chat.on_message(ChatMessage)
async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
    for item in msg.content:
        if isinstance(item, TextContent):
            ctx.logger.info(f"💬 Reply from {sender}: {item.text}")
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id
    ))

@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    ctx.logger.info("✅ Message acknowledged")

agent.include(chat, publish_manifest=True)

@agent.on_event("startup")
async def say_hello(ctx: Context):
    ctx.logger.info("Sending hello to chatmate-fetcher...")
    await ctx.send(TARGET, ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[TextContent(type="text", text="Hello from my laptop!")],
    ))

if __name__ == "__main__":
    agent.run()
