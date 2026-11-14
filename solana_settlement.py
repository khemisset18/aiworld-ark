"""Solana Devnet payment verification for AI WORLD.

Proof of concept ONLY. No mainnet collection until independent audit and escrow.
Read-only RPC calls: this module never signs or sends a transaction.
"""
from __future__ import annotations

import os
import re

import httpx

TREASURY = "8XiHsbV9jFzc31aLpKBGycKdTGQXQuBWZE8xFgRhEvZ6"
LAMPORTS_PER_SOL = 1_000_000_000
DEVNET_RPC = "https://api.devnet.solana.com"
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError("Invalid base58")
    n = 0
    for char in value:
        if char not in ALPHABET:
            raise ValueError("Invalid base58")
        n = n * 58 + ALPHABET.index(char)
    encoded = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + encoded


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    chars = []
    while n:
        n, rem = divmod(n, 58)
        chars.append(ALPHABET[rem])
    prefix = "1" * (len(data) - len(data.lstrip(b"\0")))
    return prefix + "".join(reversed(chars))


def valid_address(address: str) -> bool:
    try:
        return len(b58decode(address)) == 32
    except ValueError:
        return False


def get_rpc_url() -> str:
    if os.environ.get("ARK_SOLANA_NETWORK", "devnet") != "devnet":
        raise RuntimeError("Mainnet disabled; independent security audit required")
    # Hard-pin the public Devnet RPC. A user-provided mainnet URL must never
    # silently enable real-money settlement in this experimental application.
    return DEVNET_RPC


def billing_enabled() -> bool:
    return os.environ.get("ARK_BILLING_ENABLED") == "1" and os.environ.get(
        "ARK_SOLANA_NETWORK", "devnet") == "devnet"


def _transaction(signature: str) -> dict | None:
    if not isinstance(signature, str) or len(b58decode(signature)) != 64:
        raise ValueError("Invalid Solana transaction signature")
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
               "params": [signature, {"encoding": "jsonParsed",
                                     "commitment": "finalized",
                                     "maxSupportedTransactionVersion": 0}]}
    with httpx.Client(timeout=12.0) as client:
        response = client.post(get_rpc_url(), json=payload)
        response.raise_for_status()
        result = response.json()
    if result.get("error"):
        raise RuntimeError("Solana RPC error")
    return result.get("result")


def verify_transfers(signature: str, *, memo: str, expected: dict[str, int],
                     issued: int, expires: int) -> bool:
    """Require finalized transaction, exact memo, same sender, exact SOL transfers.

    In particular: one transaction cannot be reused for multiple invoices.
    That replay protection is enforced separately by the database's unique
    payment_signatures table.
    """
    if not expected or len(expected) > 2:
        return False
    if any(not valid_address(a) or type(v) is not int or v <= 0
           for a, v in expected.items()):
        return False
    tx = _transaction(signature)
    if not isinstance(tx, dict):
        return False
    meta = tx.get("meta") or {}
    if meta.get("err", "missing") is not None:
        return False
    time = tx.get("blockTime")
    if type(time) is not int or not issued <= time <= expires:
        return False
    message = (tx.get("transaction") or {}).get("message") or {}
    if signature not in ((tx.get("transaction") or {}).get("signatures") or []):
        return False
    instructions = message.get("instructions") or []
    if not isinstance(instructions, list):
        return False
    memos = []
    transfers = {}
    sources = set()
    for ins in instructions:
        if not isinstance(ins, dict):
            continue
        program = ins.get("program")
        if program == "spl-memo" or ins.get("programId") == MEMO_PROGRAM:
            parsed = ins.get("parsed")
            if isinstance(parsed, dict):
                parsed = parsed.get("memo")
            memos.append(parsed)
        if program == "system":
            parsed = ins.get("parsed")
            if not isinstance(parsed, dict) or parsed.get("type") != "transfer":
                continue
            info = parsed.get("info") or {}
            to_addr, sender, amount = info.get("destination"), info.get("source"), info.get("lamports")
            if to_addr in expected:
                if not valid_address(sender) or type(amount) is not int or amount <= 0:
                    return False
                sources.add(sender)
                transfers[to_addr] = transfers.get(to_addr, 0) + amount
    return memos == [memo] and len(sources) == 1 and transfers == expected


def payment_receipt_table(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS payment_signatures(
        signature TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        reference_id TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""")
