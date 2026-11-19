import json
import time
from collections.abc import Callable
from typing import Any, TypeVar

from crewai import Agent, BaseLLM
from crewai.flow.flow import Flow, listen, router, start
from pydantic import BaseModel, ValidationError

from trader_agent.agents.llm import ChatModel
from trader_agent.agents.models import (
    PROMPT_VERSION,
    Critique,
    Outcome,
    Proposal,
    ProposalContext,
    validate_proposal,
)

M = TypeVar("M", bound=BaseModel)

PROPOSER = {
    "role": "Spot trade proposer",
    "goal": "Decide whether to act on a deterministic rule signal for one Nobitex IRT market.",
    "backstory": (
        "You review one closed-candle rule signal at a time. You never size orders, never "
        "move stops, and never see balances. You either take the signal or pass on it."
    ),
}

CRITIC = {
    "role": "Independent trade critic",
    "goal": "Find reasons a proposed action is unsafe or unsupported by the given data.",
    "backstory": (
        "You did not write the proposal. Approve only when the data clearly supports it. "
        "Reject when it does not. Abstain when the data is not enough to judge."
    ),
}


GLOSSARY = (
    "How to read the data:\n"
    '- signal "entry": the rules want to BUY and open a new long position. '
    "position.held is false, which is expected. rule_stop is the protective stop price "
    "that will be placed below entry; atr is the 15m average true range.\n"
    '- signal "exit": the rules want to SELL the whole bot-managed position. '
    "position.entry_price and position.stop describe that position; the stop stays "
    "in place whether or not you exit now.\n"
    "- close is the last closed 15m candle close in IRT. profile_24h (POC, VAH, VAL) and "
    "trend_1d_up may be null when unavailable; null is not a reason to object by itself.\n"
    '- action "take" means: carry out this signal now (entry: buy; exit: sell). '
    'action "pass" means: do nothing this candle. "take" never means take-profit.\n'
    "- Position size, fees, and risk limits are handled by separate code; do not judge them.\n"
)


def proposal_prompt(context: ProposalContext) -> str:
    return (
        f"Prompt version {PROMPT_VERSION}.\n{GLOSSARY}\n"
        "Rule signal and market context (JSON):\n"
        f"{context.model_dump_json()}\n\n"
        "Decide whether to take or pass on this signal.\n"
        "Reply with one JSON object only, with keys: "
        '"symbol" (copy from context), "signal" (copy from context), '
        '"action" ("take" or "pass"), "confidence" (0 to 1), "rationale" (short text).'
    )


def critic_prompt(context: ProposalContext, proposal: Proposal) -> str:
    return (
        f"Prompt version {PROMPT_VERSION}.\n{GLOSSARY}\n"
        "Rule signal and market context (JSON):\n"
        f"{context.model_dump_json()}\n\n"
        "Proposal to review (JSON):\n"
        f"{proposal.model_dump_json()}\n\n"
        'Answer "approve" if the data supports the proposed action, "reject" if the data '
        'contradicts it, "abstain" only if the data is too thin to judge either way.\n'
        "Reply with one JSON object only, with keys: "
        '"verdict" ("approve", "reject", or "abstain") and "reason" (short text).'
    )


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)


class CrewModel(BaseLLM):
    chat: Any = None

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        clean = [{"role": str(m["role"]), "content": _text(m.get("content"))} for m in messages]
        reply: str = self.chat.complete(clean)
        return reply


def make_agent(chat: ChatModel, spec: dict[str, str]) -> Agent:
    return Agent(
        **spec,
        llm=CrewModel(model=chat.name, chat=chat),
        tools=[],
        max_iter=1,
        max_retry_limit=0,
        allow_delegation=False,
        verbose=False,
    )


class Expired(Exception):
    pass


class ReviewState(BaseModel):
    proposal: Proposal | None = None
    critique: Critique | None = None
    outcome: Outcome | None = None


class Session:
    def __init__(
        self,
        chat: ChatModel,
        context: ProposalContext,
        deadline: float,
        clock: Callable[[], float],
    ) -> None:
        self.context = context
        self.deadline = deadline
        self.clock = clock
        self.proposer = make_agent(chat, PROPOSER)
        self.critic = make_agent(chat, CRITIC)

    def ask(self, agent: Agent, prompt: str, schema: type[M]) -> M | str:
        error = "no attempt made"
        for _ in range(2):
            if self.clock() > self.deadline:
                raise Expired
            try:
                out = agent.kickoff(prompt, response_format=schema)
                parsed = getattr(out, "pydantic", None)
                if isinstance(parsed, schema):
                    return parsed
                return schema.model_validate_json(str(getattr(out, "raw", "")))
            except ValidationError:
                error = "output did not match the schema"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:200]
        return error


class ReviewFlow(Flow[ReviewState]):
    session: Any = None

    def fail(self, who: str, error: str) -> None:
        self.state.outcome = Outcome(
            approved=False,
            reason=f"{who} failed: {error}",
            proposal=self.state.proposal,
            model_failure=True,
        )

    @start()
    def propose(self) -> None:
        result = self.session.ask(
            self.session.proposer, proposal_prompt(self.session.context), Proposal
        )
        if isinstance(result, str):
            self.fail("proposer", result)
            return
        self.state.proposal = result
        invalid = validate_proposal(result, self.session.context)
        if invalid is not None:
            self.state.outcome = Outcome(approved=False, reason=invalid, proposal=result)
        elif result.action == "pass":
            self.state.outcome = Outcome(approved=False, reason="proposer passed", proposal=result)

    @router(propose)
    def route(self) -> str:
        return "done" if self.state.outcome is not None else "review"

    @listen("review")
    def critique(self) -> None:
        assert self.state.proposal is not None
        s = self.session
        result = s.ask(s.critic, critic_prompt(s.context, self.state.proposal), Critique)
        if isinstance(result, str):
            self.fail("critic", result)
            return
        self.state.critique = result
        self.state.outcome = Outcome(
            approved=result.verdict == "approve",
            reason=f"critic {result.verdict}",
            proposal=self.state.proposal,
            critique=result,
        )


class Reviewer:
    def __init__(
        self,
        chat: ChatModel,
        alert: Callable[[str], None],
        deadline_s: float = 300,
        clock: Callable[[], float] = time.monotonic,
        alert_after: int = 3,
    ) -> None:
        self.chat = chat
        self.alert = alert
        self.deadline_s = deadline_s
        self.clock = clock
        self.alert_after = alert_after
        self.consecutive_failures = 0

    def review(self, context: ProposalContext) -> Outcome:
        session = Session(self.chat, context, self.clock() + self.deadline_s, self.clock)
        flow = ReviewFlow(session=session, suppress_flow_events=True, tracing=False)
        try:
            flow.kickoff()
            outcome = flow.state.outcome or Outcome(
                approved=False, reason="flow ended without a decision", model_failure=True
            )
        except Expired:
            outcome = Outcome(
                approved=False,
                reason="signal expired during review",
                proposal=flow.state.proposal,
                model_failure=True,
            )
        except Exception as exc:
            outcome = Outcome(
                approved=False,
                reason=f"flow error: {type(exc).__name__}: {exc}"[:200],
                model_failure=True,
            )
        if outcome.model_failure:
            self.consecutive_failures += 1
            if self.consecutive_failures == self.alert_after:
                self.alert(
                    f"[agents] {self.consecutive_failures} consecutive review failures; "
                    f"last: {outcome.reason}"
                )
        else:
            self.consecutive_failures = 0
        return outcome


def outcome_record(outcome: Outcome) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(outcome.model_dump_json())
    body["prompt_version"] = PROMPT_VERSION
    return body
