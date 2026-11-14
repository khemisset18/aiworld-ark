"""Safety guardrails for prototype source: static review, NOT Solana execution."""
import re
from pathlib import Path

from solana_settlement import TREASURY, b58decode

PROGRAM = Path(__file__).parent / "programs/aiworld_escrow/src/lib.rs"


def test_escrow_is_restricted_to_consented_program_wallets():
    s = PROGRAM.read_text(encoding="utf-8")
    assert "pub buyer: Signer<'info>" in s
    assert "pub provider: Signer<'info>" in s
    assert "pub arbiter: Signer<'info>" in s
    assert "has_one = provider" in s
    assert "has_one = buyer" in s
    assert "has_one = arbiter" in s
    assert "address = escrow.provider" in s
    assert "address = escrow.buyer" in s
    assert "address = TREASURY" in s
    assert "pub fn refund_undelivered" in s
    assert "pub fn accept_delivery" in s
    assert "pub fn escalate_undecided" in s
    assert "pub fn arbitrate" in s
    assert "pub fn open_dispute" in s
    assert "pub fn submit_delivery" in s
    assert "init, payer = buyer" in s
    assert "pub escrow: Account<'info, EscrowState>" in s
    assert "ctx.accounts.escrow.sub_lamports(gross)?" in s
    assert "system_program::transfer(transfer, gross_lamports)?" in s
    assert "pub const FEE_BPS: u64 = 300" in s
    assert "pub const BPS: u64 = 10_000" in s
    assert "ctx.accounts.escrow.status = REFUNDED" in s
    assert "ctx.accounts.escrow.status = RELEASED" in s
    assert "ctx.accounts.escrow.status == FUNDED" in s
    assert "ctx.accounts.escrow.status == DELIVERED" in s
    assert "ctx.accounts.escrow.status == DISPUTED" in s


def test_program_treasury_is_exactly_founder_address():
    s = PROGRAM.read_text(encoding="utf-8")
    m = re.search(r"pub const TREASURY: Pubkey = Pubkey::new_from_array\(\[([^\]]+)\]\)", s)
    assert m
    numbers = bytes(int(x) for x in m.group(1).split(",") if x.strip())
    assert numbers == b58decode(TREASURY)


def test_payment_lifecycle_retains_an_immutable_tombstone():
    s = PROGRAM.read_text(encoding="utf-8")
    assert "seeds = [b\"escrow\", buyer.key().as_ref(), &job_id.to_le_bytes()]" in s
    assert "status: u8" in s
    assert not re.search(r"close\s*=", s)
    assert "MAX_PAYMENT" in s and "MIN_PAYMENT" in s
    assert "MAX_DEADLINE_SECONDS" in s


def test_rust_ci_exists_but_it_is_not_an_onchain_audit():
    y = (Path(__file__).parent / ".github/workflows/escrow-rust.yml").read_text()
    assert "cargo check" in y
    assert "cargo test" in y
    assert "not a validator test" in y
