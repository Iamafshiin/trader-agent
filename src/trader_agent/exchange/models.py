from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class Kind(StrEnum):
    LIMIT = "limit"
    STOP_MARKET = "stop_market"


class Status(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


TRANSITIONS: dict[Status, set[Status]] = {
    Status.NEW: {Status.ACTIVE, Status.FILLED, Status.REJECTED},
    Status.ACTIVE: {Status.FILLED, Status.CANCELED},
    Status.FILLED: set(),
    Status.CANCELED: set(),
    Status.REJECTED: set(),
}


class InvalidTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketRules:
    symbol: str
    amount_step: Decimal
    price_step: Decimal
    min_notional: Decimal

    def floor_amount(self, qty: Decimal) -> Decimal:
        return (qty / self.amount_step).to_integral_value(rounding=ROUND_DOWN) * self.amount_step

    def floor_price(self, price: Decimal) -> Decimal:
        return (price / self.price_step).to_integral_value(rounding=ROUND_DOWN) * self.price_step


@dataclass
class Order:
    client_id: str
    symbol: str
    side: Side
    kind: Kind
    amount: Decimal
    price: Decimal | None = None
    stop_price: Decimal | None = None
    status: Status = Status.NEW
    fill_price: Decimal | None = None
    fee: Decimal = Decimal(0)
    reason: str = ""
    history: list[Status] = field(default_factory=list)

    def move(self, to: Status) -> None:
        if to not in TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.client_id}: {self.status} -> {to}")
        self.history.append(self.status)
        self.status = to
