"""Every card your agent can send must pass ASI:One's validation."""

import os
import sys
from pathlib import Path

os.environ.setdefault("AGENT_SEED_PHRASE", "unit test seed phrase, not a real agent")
os.environ["AGENTVERSE_API_KEY"] = ""  # never connect to Agentverse from tests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_hackkit.cards import collect_actions, validate

import agent


def test_menu_card_is_valid() -> None:
    card = agent.menu()
    assert validate(card.kind, card.payload) == []


def test_every_menu_button_has_a_handler() -> None:
    actions = collect_actions(agent.menu().payload)
    assert actions <= set(agent.agent._action_handlers)
