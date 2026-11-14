"""Pure, off-chain demonstration of a reversible compute escrow state machine.

NO ASSETS ARE DEPOSITED IN THIS MODULE. This cannot serve as a Solana escrow.
An independently audited, non-custodial on-chain program (or licensed provider)
would be needed to enforce these transitions for actual money.
"""
from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    CREATED = "created"
    LOCKED = "locked_simulated"
    DELIVERED = "delivered"
    DISPUTED = "disputed"
    RELEASED = "released_simulated"
    REFUNDED = "refunded_simulated"


@dataclass
class EscrowSimulation:
    buyer: str
    provider: str
    gross_lamports: int
    deadline: int
    state: State = State.CREATED
    delivered_digest: str | None = None

    def __post_init__(self):
        if not isinstance(self.buyer, str) or not isinstance(self.provider, str) or not self.buyer or not self.provider or self.buyer == self.provider:
            raise ValueError("Distinct participants required")
        if type(self.gross_lamports) is not int or self.gross_lamports < 34 or self.gross_lamports > 10**15:
            raise ValueError("Invalid escrow amount: must cover 3% fee and provider payment")
        if type(self.deadline) is not int or self.deadline <= 0:
            raise ValueError("Invalid deadline")

    @property
    def split(self):
        fee = (self.gross_lamports * 300 + 9999) // 10000
        return {"fee_lamports": fee, "provider_lamports": self.gross_lamports - fee}

    def lock(self, actor, *, settlement_confirmed: bool):
        if actor != self.buyer or self.state is not State.CREATED or settlement_confirmed is not True:
            raise PermissionError("Only a confirmed buyer deposit can lock escrow")
        self.state = State.LOCKED

    def deliver(self, actor, *, digest: str, now: int):
        if actor != self.provider or self.state is not State.LOCKED or now > self.deadline:
            raise PermissionError("Provider can deliver only before deadline")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Expected SHA-256 proof digest")
        self.delivered_digest = digest
        self.state = State.DELIVERED

    def accept(self, actor):
        if actor != self.buyer or self.state is not State.DELIVERED:
            raise PermissionError("Only buyer can accept valid delivery")
        self.state = State.RELEASED
        return self.split

    def dispute(self, actor):
        if actor != self.buyer or self.state not in (State.LOCKED, State.DELIVERED):
            raise PermissionError("Only buyer can dispute open escrow")
        self.state = State.DISPUTED

    def timeout_refund(self, actor, *, now: int):
        if actor != self.buyer or self.state is not State.LOCKED or now <= self.deadline:
            raise PermissionError("Buyer can refund undelivered job only after deadline")
        self.state = State.REFUNDED
        return self.gross_lamports

    def resolve_dispute(self, *, authority: str, decision: str):
        # Deliberately unusable: the independent arbitrator/on-chain policy
        # has not been defined. Never let a server string impersonate an arbitrator.
        raise NotImplementedError("Dispute resolution needs audited on-chain authorization")
