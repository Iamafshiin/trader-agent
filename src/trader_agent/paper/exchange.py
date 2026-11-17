import itertools
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from trader_agent.exchange.models import Kind, MarketRules, Order, Side, Status


@dataclass(frozen=True)
class Book:
    bid: Decimal | None
    ask: Decimal | None
    at_ms: int


@dataclass(frozen=True)
class Costs:
    maker_fee: Decimal
    taker_fee: Decimal
    slippage_normal: Decimal
    slippage_stop: Decimal


@dataclass(frozen=True)
class Fill:
    order: Order
    price: Decimal
    fee: Decimal
    slippage: Decimal
    at_ms: int


@dataclass
class PaperAccount:
    cash: Decimal
    holdings: dict[str, Decimal] = field(default_factory=dict)
    stops: dict[str, Order] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "cash": str(self.cash),
            "holdings": {k: str(v) for k, v in self.holdings.items()},
            "stops": {
                k: {"client_id": o.client_id, "amount": str(o.amount), "stop": str(o.stop_price)}
                for k, o in self.stops.items()
            },
        }

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> "PaperAccount":
        acct = cls(Decimal(body["cash"]), {k: Decimal(v) for k, v in body["holdings"].items()})
        for sym, s in body["stops"].items():
            acct.stops[sym] = Order(
                s["client_id"],
                sym,
                Side.SELL,
                Kind.STOP_MARKET,
                Decimal(s["amount"]),
                stop_price=Decimal(s["stop"]),
                status=Status.ACTIVE,
            )
        return acct


def asset_of(symbol: str) -> str:
    return symbol.removesuffix("IRT")


class PaperExchange:
    def __init__(self, account: PaperAccount, costs: Costs) -> None:
        self.account = account
        self.costs = costs
        self._ids = itertools.count(1)

    def next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids)}"

    def equity(self, books: dict[str, Book]) -> Decimal:
        total = self.account.cash
        for asset, qty in self.account.holdings.items():
            book = books.get(f"{asset}IRT")
            if qty and (book is None or book.bid is None):
                raise LookupError(f"no bid to mark {asset}")
            if qty and book is not None and book.bid is not None:
                total += qty * book.bid
        return total

    def exposure(self, books: dict[str, Book]) -> Decimal:
        return self.equity(books) - self.account.cash

    def market_buy_at_touch(self, order: Order, book: Book, now_ms: int) -> Fill:
        if book.ask is None:
            order.move(Status.REJECTED)
            raise ValueError("empty book")
        price = book.ask * (1 + self.costs.slippage_normal)
        cost = order.amount * price
        if cost > self.account.cash:
            order.move(Status.REJECTED)
            raise ValueError("insufficient cash")
        fee = order.amount * self.costs.taker_fee
        asset = asset_of(order.symbol)
        self.account.cash -= cost
        self.account.holdings[asset] = self.account.holdings.get(asset, Decimal(0)) + (
            order.amount - fee
        )
        return self._filled(
            order, price, fee, order.amount * book.ask * self.costs.slippage_normal, now_ms
        )

    def market_sell_at_touch(
        self, order: Order, book: Book, now_ms: int, stop: bool = False
    ) -> Fill:
        asset = asset_of(order.symbol)
        held = self.account.holdings.get(asset, Decimal(0))
        if book.bid is None or order.amount > held:
            order.move(Status.REJECTED)
            raise ValueError("empty book or amount above holdings")
        slip = self.costs.slippage_stop if stop else self.costs.slippage_normal
        price = book.bid * (1 - slip)
        gross = order.amount * price
        fee = gross * self.costs.taker_fee
        self.account.holdings[asset] = held - order.amount
        self.account.cash += gross - fee
        return self._filled(order, price, fee, order.amount * book.bid * slip, now_ms)

    def _filled(
        self, order: Order, price: Decimal, fee: Decimal, slip: Decimal, now_ms: int
    ) -> Fill:
        order.move(Status.FILLED)
        order.fill_price = price
        order.fee = fee
        return Fill(order, price, fee, slip, now_ms)

    def place_stop(self, order: Order) -> None:
        if order.symbol in self.account.stops:
            raise ValueError("stop already active")
        order.move(Status.ACTIVE)
        self.account.stops[order.symbol] = order

    def cancel_stop(self, symbol: str) -> Order | None:
        order = self.account.stops.pop(symbol, None)
        if order is not None:
            order.move(Status.CANCELED)
        return order

    def on_trade(self, symbol: str, price: Decimal, book: Book, now_ms: int) -> Fill | None:
        stop = self.account.stops.get(symbol)
        if stop is None or stop.stop_price is None or price > stop.stop_price:
            return None
        del self.account.stops[symbol]
        touch = book if book.bid is not None else Book(price, book.ask, now_ms)
        return self.market_sell_at_touch(stop, touch, now_ms, stop=True)

    def rules_check(self, rules: MarketRules, amount: Decimal, price: Decimal) -> bool:
        return amount > 0 and amount * price >= rules.min_notional
