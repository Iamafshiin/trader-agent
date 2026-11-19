import json
import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from trader_agent.agents.flow import Reviewer, outcome_record
from trader_agent.agents.llm import ModelError, OpenAICompatibleModel
from trader_agent.agents.models import (
    PROMPT_VERSION,
    PositionView,
    ProposalContext,
    context_for,
)
from trader_agent.strategy.tcp_vp import EntrySignal, ExitSignal

D = Decimal
ENTRY = EntrySignal("BTCIRT", 1_700_000_000, D(100), D(5), D(5), D(95))
FLAT = PositionView(held=False)
PROFILE = {"poc": D(101), "vah": D(105), "val": D(97), "volume": D(12)}


def proposal(action: str = "take", symbol: str = "BTCIRT", signal: str = "entry") -> str:
    return json.dumps(
        {
            "symbol": symbol,
            "signal": signal,
            "action": action,
            "confidence": 0.7,
            "rationale": "trend and profile agree",
        }
    )


def critique(verdict: str) -> str:
    return json.dumps({"verdict": verdict, "reason": "checked"})


class StubChat:
    name = "stub-model"

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Clock:
    def __init__(self, step: float = 0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        current = self.now
        self.now += self.step
        return current


def entry_context() -> ProposalContext:
    return context_for(ENTRY, D(102), FLAT, PROFILE, True)


def run(chat: StubChat, context: ProposalContext | None = None, alerts: list[str] | None = None):
    reviewer = Reviewer(chat, (alerts if alerts is not None else []).append)
    return reviewer.review(context or entry_context())


def test_take_and_approve_is_the_only_approved_path() -> None:
    chat = StubChat(proposal(), critique("approve"))
    outcome = run(chat)
    assert outcome.approved
    assert outcome.critique is not None and outcome.critique.verdict == "approve"
    assert len(chat.calls) == 2


@pytest.mark.parametrize("verdict", ["reject", "abstain"])
def test_critic_reject_or_abstain_skips(verdict: str) -> None:
    outcome = run(StubChat(proposal(), critique(verdict)))
    assert not outcome.approved
    assert not outcome.model_failure
    assert outcome.reason == f"critic {verdict}"


def test_proposer_pass_skips_without_calling_critic() -> None:
    chat = StubChat(proposal("pass"))
    outcome = run(chat)
    assert not outcome.approved and not outcome.model_failure
    assert len(chat.calls) == 1


def test_invalid_output_retries_once_then_fails_closed() -> None:
    chat = StubChat("not json", '{"action": "maybe"}')
    outcome = run(chat)
    assert not outcome.approved and outcome.model_failure
    assert outcome.reason.startswith("proposer failed")
    assert len(chat.calls) == 2


def test_one_retry_recovers_from_a_bad_reply() -> None:
    chat = StubChat("garbage", proposal(), critique("approve"))
    assert run(chat).approved
    assert len(chat.calls) == 3


def test_model_errors_retry_once_then_fail_closed() -> None:
    chat = StubChat(ModelError("timeout"), ModelError("timeout"))
    outcome = run(chat)
    assert not outcome.approved and outcome.model_failure
    assert len(chat.calls) == 2


def test_unparseable_critic_fails_closed() -> None:
    outcome = run(StubChat(proposal(), "{}", "nope"))
    assert not outcome.approved and outcome.model_failure
    assert outcome.reason.startswith("critic failed")


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        (proposal(symbol="ETHIRT"), "symbol"),
        (proposal(signal="exit"), "signal"),
    ],
)
def test_proposal_that_does_not_match_the_signal_is_rejected(reply: str, reason: str) -> None:
    chat = StubChat(reply)
    outcome = run(chat)
    assert not outcome.approved and reason in outcome.reason
    assert len(chat.calls) == 1


def test_exit_without_bot_position_is_rejected() -> None:
    context = context_for(ExitSignal("BTCIRT", 1, "15m trend turned down"), D(90), FLAT)
    chat = StubChat(proposal(signal="exit"))
    outcome = run(chat, context)
    assert not outcome.approved and "position" in outcome.reason


def test_held_exit_can_be_approved() -> None:
    held = PositionView(held=True, entry_price=D(100), stop=D(95))
    context = context_for(ExitSignal("BTCIRT", 1, "15m trend turned down"), D(90), held)
    assert run(StubChat(proposal(signal="exit"), critique("approve")), context).approved


def test_signal_expiry_during_review_fails_closed() -> None:
    reviewer = Reviewer(StubChat(proposal(), critique("approve")), [].append, 300, Clock(200))
    outcome = reviewer.review(entry_context())
    assert not outcome.approved and outcome.model_failure
    assert "expired" in outcome.reason


def test_alert_after_three_consecutive_failures_and_reset_on_success() -> None:
    alerts: list[str] = []
    bad = ["x", "x"]
    chat = StubChat(*bad, *bad, proposal("pass"), *bad, *bad, *bad)
    reviewer = Reviewer(chat, alerts.append)
    for _ in range(5):
        reviewer.review(entry_context())
    assert alerts == []
    reviewer.review(entry_context())
    assert len(alerts) == 1 and "3 consecutive" in alerts[0]


def test_prompts_carry_no_account_data() -> None:
    banned = {"equity", "balance", "cash", "exposure", "api_key", "secret", "holdings"}
    names: set[str] = set()
    for model in (ProposalContext, PositionView):
        names |= set(model.model_fields)
    assert not names & banned
    chat = StubChat(proposal(), critique("approve"))
    run(chat)
    text = json.dumps(chat.calls).lower()
    assert not any(f'\\"{word}' in text for word in banned)
    assert PROMPT_VERSION in text


def test_context_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        ProposalContext.model_validate({**entry_context().model_dump(), "equity": "1000000"})


def test_outcome_record_is_json_with_prompt_version() -> None:
    record = outcome_record(run(StubChat(proposal(), critique("approve"))))
    assert record["approved"] is True
    assert record["prompt_version"] == PROMPT_VERSION
    json.dumps(record)


def test_crewai_is_imported_only_inside_agents() -> None:
    src = Path(__file__).resolve().parent.parent / "src" / "trader_agent"
    pattern = re.compile(r"^\s*(import|from)\s+crewai\b", re.M)
    offenders = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8")) and p.relative_to(src).parts[0] != "agents"
    ]
    assert offenders == []


def test_openai_compatible_model_sends_deterministic_json_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    model = OpenAICompatibleModel(
        "https://llm.example/v1/", "k", "m-1", transport=httpx.MockTransport(handler)
    )
    assert model.complete([{"role": "user", "content": "hi"}]) == "{}"
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://llm.example/v1/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer k"
    assert body["temperature"] == 0 and body["model"] == "m-1"


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500), httpx.Response(200, json={"choices": []})],
)
def test_openai_compatible_model_raises_model_error(response: httpx.Response) -> None:
    model = OpenAICompatibleModel(
        "https://llm.example/v1", "k", "m", transport=httpx.MockTransport(lambda _: response)
    )
    with pytest.raises(ModelError):
        model.complete([{"role": "user", "content": "hi"}])


def test_openai_compatible_model_requires_https() -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleModel("http://llm.example", "k", "m")
