"""ChatMateFetcher: a Fetch.ai agent built with fetch-hackkit.

Run it:  uv run python agent.py
Then chat with it on ASI:One (https://asi1.ai):  @chatmatefetcher hi

Start here: change the description, replace get_weather with your own tools,
and add cards for the steps of your workflow. AGENTS.md has every pattern.
"""

from __future__ import annotations

import os

import httpx
from fetch_hackkit import ASI1, ASI1Error, HackAgent, cards, history, remember

agent = HackAgent(
    name="chatmatefetcher",
    handle=os.getenv("AGENT_HANDLE") or None,
    # One sentence ASI:One users would search for. ASI:One routes by this + README.md.
    description="coding agent to verify if code is ready for merge",
    # connects to Agentverse mailbox
    mailbox=True,
    readme_path="README.md",
)

SYSTEM = (
    "You are ChatMateFetcher, an agent on Fetch.ai. Be concise. "
    "Use your tools for facts instead of guessing."
)

GREETINGS = {"hi", "hello", "hey", "menu", "start", "help"}


async def get_prompt(code_to_review: str) -> str:
    """Code to be reviewed and verified

    Args:
        prompt: code to be reviewed.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"https://wttr.in/{code_to_review}", params={"format": "3000"})
        resp.raise_for_status()
        return resp.text.strip()


def menu() -> cards.Card:
    return cards.carousel(
        "ChatMateFetcher",
        [
            cards.item(
                "ask",
                "Ask a code question",
                action="ask_help",
                subtitle="ASI:One answers, calling tools when needed",
            ),
            cards.item(
                "about", "What can you do?", action="about", subtitle="A quick tour of this agent"
            ),
        ],
        narration="Hi! I'm **ChatMateFetcher**. Pick an option or just ask me something.",
    )


@agent.on_text
async def on_text(ctx, msg):
    """Greetings open the menu; everything else goes to ASI:One with tools."""
    if msg.text.strip().lower() in GREETINGS:
        return menu()
    try:
        llm = ASI1()
    except ASI1Error:
        return "Add ASI_ONE_API_KEY to .env so I can answer questions."
    past = history(ctx, msg.session)
    reply = await llm.run_tools(
        [*past, {"role": "user", "content": msg.text}],
        tools=[get_prompt],
        system=SYSTEM,
    )
    remember(ctx, msg.session, "user", msg.text)
    remember(ctx, msg.session, "assistant", reply)
    return reply


@agent.on_action("ask_help")
async def ask_help(ctx, msg, sel):
    return "Ask me anything. Try: *how to code a binary search in python?"


@agent.on_action("about")
async def about(ctx, msg, sel):
    return cards.info(
        "About ChatMateFetcher",
        rows={
            "Talks via": "Agent Chat Protocol (ASI:One)",
            "Brain": "ASI:One LLM with tool calling",
            "Tools": "get_prompt",
        },
        narration="Here's what I'm built from Fetch.ai + Meta API.",
    )


if __name__ == "__main__":
    agent.run()
