from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from trader_agent.strategy.tcp_vp import EntrySignal, ExitSignal

PROMPT_VERSION = "b7-3"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProfileView(Frozen):
    poc: Decimal
    vah: Decimal
    val: Decimal


class PositionView(Frozen):
    held: bool
    entry_price: Decimal | None = None
    stop: Decimal | None = None


class ProposalContext(Frozen):
    symbol: str
    signal: Literal["entry", "exit"]
    candle_time: int
    close: Decimal
    rule_reason: str
    atr: Decimal | None = None
    rule_stop: Decimal | None = None
    profile_24h: ProfileView | None = None
    trend_1d_up: bool | None = None
    recent_closes_15m: tuple[Decimal, ...] = ()
    position: PositionView


class Proposal(Frozen):
    symbol: str
    signal: Literal["entry", "exit"]
    action: Literal["take", "pass"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=600)


class Critique(Frozen):
    verdict: Literal["approve", "reject", "abstain"]
    reason: str = Field(min_length=1, max_length=600)


class Outcome(Frozen):
    approved: bool
    reason: str
    proposal: Proposal | None = None
    critique: Critique | None = None
    model_failure: bool = False


def context_for(
    signal: EntrySignal | ExitSignal,
    close: Decimal,
    position: PositionView,
    profile_24h: dict[str, Decimal] | None = None,
    trend_1d_up: bool | None = None,
    recent_closes: Sequence[Decimal] = (),
) -> ProposalContext:
    profile = (
        None
        if profile_24h is None
        else ProfileView(poc=profile_24h["poc"], vah=profile_24h["vah"], val=profile_24h["val"])
    )
    if isinstance(signal, EntrySignal):
        return ProposalContext(
            symbol=signal.symbol,
            signal="entry",
            candle_time=signal.candle_time,
            close=close,
            rule_reason="pullback reclaimed the fast EMA in a 15m and 1h uptrend",
            atr=signal.atr,
            rule_stop=signal.stop,
            profile_24h=profile,
            trend_1d_up=trend_1d_up,
            recent_closes_15m=tuple(recent_closes),
            position=position,
        )
    return ProposalContext(
        symbol=signal.symbol,
        signal="exit",
        candle_time=signal.candle_time,
        close=close,
        rule_reason=signal.reason,
        profile_24h=profile,
        trend_1d_up=trend_1d_up,
        recent_closes_15m=tuple(recent_closes),
        position=position,
    )


def validate_proposal(proposal: Proposal, context: ProposalContext) -> str | None:
    if proposal.symbol != context.symbol:
        return "proposal symbol does not match the signal"
    if proposal.signal != context.signal:
        return "proposal signal does not match the rule signal"
    if context.signal == "exit" and not context.position.held:
        return "exit proposed without a bot-managed position"
    if context.signal == "entry" and context.position.held:
        return "entry proposed while a position is held"
    return None
