from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ProposedOrder:
    symbol: str
    side: str
    order_type: str
    qty: float
    reduce_only: bool = False
    price: float | None = None
    leverage: float | None = None


class ExchangeAdapter(ABC):
    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_open_orders(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def set_leverage(self, symbol: str, leverage: float) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, order: ProposedOrder) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        raise NotImplementedError
