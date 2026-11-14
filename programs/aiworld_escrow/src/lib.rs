//! Experimental SOL escrow for voluntary paid compute jobs.
//!
//! NOT AUDITED, NOT DEPLOYED, NOT SAFE FOR REAL FUNDS.
//! The on-chain state keeps rent as a permanent anti-replay tombstone.
//! Buyer and provider BOTH sign the initial agreement and name the independent
//! arbitrator; no founder-controlled withdrawal instruction exists.

use anchor_lang::prelude::*;
use anchor_lang::system_program::{self, Transfer};

// DEVELOPMENT PLACEHOLDER. Must regenerate with `anchor keys sync` before
// a local-validator/Devnet deployment. NEVER use for mainnet funds as-is.
declare_id!("D7znrjkS7wsRagPTDxACqrfPUccQhKQxFNYTSKNhnSMX");

pub const FEE_BPS: u64 = 300;
pub const BPS: u64 = 10_000;
pub const MIN_PAYMENT: u64 = 100;
pub const MAX_PAYMENT: u64 = 1_000_000_000_000_000;
pub const MIN_DEADLINE_SECONDS: i64 = 60;
pub const MAX_DEADLINE_SECONDS: i64 = 7 * 24 * 3600;

// Public treasury supplied by project owner. Never a private key.
pub const TREASURY: Pubkey = Pubkey::new_from_array([
    111, 223, 235, 167, 194, 18, 96, 145, 165, 38, 7, 103, 9, 232, 178, 60,
    238, 24, 181, 135, 254, 52, 195, 221, 152, 189, 31, 30, 180, 254, 125, 1,
]);

pub const FUNDED: u8 = 0;
pub const DELIVERED: u8 = 1;
pub const DISPUTED: u8 = 2;
pub const RELEASED: u8 = 3;
pub const REFUNDED: u8 = 4;

#[program]
pub mod aiworld_escrow {
    use super::*;

    /// Atomically create a PDA and transfer the exact amount from the buyer.
    /// Buyer and provider must sign the same Solana transaction, consenting to
    /// amount, deadline, exact wallet addresses and independent arbitrator.
    pub fn fund(
        ctx: Context<Fund>,
        job_id: u64,
        gross_lamports: u64,
        deadline: i64,
        arbiter_key: Pubkey,
    ) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(gross_lamports >= MIN_PAYMENT && gross_lamports <= MAX_PAYMENT,
                 EscrowError::InvalidPrice);
        let min_deadline = now.checked_add(MIN_DEADLINE_SECONDS)
            .ok_or(EscrowError::Overflow)?;
        let max_deadline = now.checked_add(MAX_DEADLINE_SECONDS)
            .ok_or(EscrowError::Overflow)?;
        require!(deadline >= min_deadline && deadline <= max_deadline,
                 EscrowError::InvalidDeadline);
        let buyer = ctx.accounts.buyer.key();
        let provider = ctx.accounts.provider.key();
        require!(buyer != provider && buyer != TREASURY && provider != TREASURY,
                 EscrowError::ConflictingWallets);
        require!(arbiter_key != buyer && arbiter_key != provider && arbiter_key != TREASURY
                 && arbiter_key != Pubkey::default(), EscrowError::ConflictingWallets);

        let (fee, _provider_share) = split_payment(gross_lamports)?;

        let escrow = &mut ctx.accounts.escrow;
        escrow.job_id = job_id;
        escrow.buyer = buyer;
        escrow.provider = provider;
        escrow.arbiter = arbiter_key;
        escrow.treasury = TREASURY;
        escrow.gross_lamports = gross_lamports;
        escrow.fee_lamports = fee;
        escrow.deadline = deadline;
        escrow.bump = ctx.bumps.escrow;
        escrow.status = FUNDED;
        escrow.proof_digest = [0u8; 32];

        // Only the buyer is debited. No fee is released at deposit time.
        let transfer = CpiContext::new(
            ctx.accounts.system_program.to_account_info(),
            Transfer {
                from: ctx.accounts.buyer.to_account_info(),
                to: ctx.accounts.escrow.to_account_info(),
            },
        );
        system_program::transfer(transfer, gross_lamports)?;
        emit!(EscrowEvent {
            escrow: ctx.accounts.escrow.key(), job_id,
            status: FUNDED, gross_lamports,
        });
        Ok(())
    }

    /// Provider posts a claim of delivery (a hash, NOT proof that the work is valid).
    pub fn submit_delivery(ctx: Context<SubmitDelivery>, digest: [u8; 32]) -> Result<()> {
        require!(ctx.accounts.escrow.status == FUNDED, EscrowError::BadState);
        require!(Clock::get()?.unix_timestamp <= ctx.accounts.escrow.deadline,
                 EscrowError::DeadlineExpired);
        require!(digest != [0u8; 32], EscrowError::MissingDigest);
        ctx.accounts.escrow.proof_digest = digest;
        ctx.accounts.escrow.status = DELIVERED;
        emit!(EscrowEvent {
            escrow: ctx.accounts.escrow.key(),
            job_id: ctx.accounts.escrow.job_id,
            status: DELIVERED,
            gross_lamports: ctx.accounts.escrow.gross_lamports,
        });
        Ok(())
    }

    /// The buyer explicitly accepts delivery: atomic 97% / 3% split.
    pub fn accept_delivery(ctx: Context<BuyerPayout>) -> Result<()> {
        require!(ctx.accounts.escrow.status == DELIVERED, EscrowError::BadState);
        let gross = ctx.accounts.escrow.gross_lamports;
        let fee = ctx.accounts.escrow.fee_lamports;
        let net = gross.checked_sub(fee).ok_or(EscrowError::Overflow)?;
        ctx.accounts.escrow.status = RELEASED; // state changes are atomic with transfers
        ctx.accounts.escrow.sub_lamports(gross)?;
        ctx.accounts.provider.add_lamports(net)?;
        ctx.accounts.treasury.add_lamports(fee)?;
        emit!(EscrowEvent {
            escrow: ctx.accounts.escrow.key(),
            job_id: ctx.accounts.escrow.job_id,
            status: RELEASED, gross_lamports: gross,
        });
        Ok(())
    }

    /// If the provider has NOT delivered by the agreed deadline, the buyer
    /// recovers the entire gross amount. AI WORLD collects NO fee.
    pub fn refund_undelivered(ctx: Context<BuyerRefund>) -> Result<()> {
        require!(ctx.accounts.escrow.status == FUNDED, EscrowError::BadState);
        require!(Clock::get()?.unix_timestamp > ctx.accounts.escrow.deadline,
                 EscrowError::DeadlineNotReached);
        let gross = ctx.accounts.escrow.gross_lamports;
        ctx.accounts.escrow.status = REFUNDED;
        ctx.accounts.escrow.sub_lamports(gross)?;
        ctx.accounts.buyer.add_lamports(gross)?;
        emit!(EscrowEvent {
            escrow: ctx.accounts.escrow.key(),
            job_id: ctx.accounts.escrow.job_id,
            status: REFUNDED, gross_lamports: gross,
        });
        Ok(())
    }

    /// Buyer can contest a delivered result. Funds stay immobilized.
    pub fn open_dispute(ctx: Context<BuyerRefund>) -> Result<()> {
        require!(ctx.accounts.escrow.status == DELIVERED, EscrowError::BadState);
        ctx.accounts.escrow.status = DISPUTED;
        emit!(EscrowEvent {
            escrow: ctx.accounts.escrow.key(),
            job_id: ctx.accounts.escrow.job_id,
            status: DISPUTED, gross_lamports: ctx.accounts.escrow.gross_lamports,
        });
        Ok(())
    }

    /// A provider must be able to request arbitration if the buyer neither
    /// accepts nor disputes a delivered result. Buyer cannot keep funds frozen
    /// without an escalation path, although arbitrator liveness is still a risk.
    pub fn escalate_undecided(ctx: Context<SubmitDelivery>) -> Result<()> {
        require!(ctx.accounts.escrow.status == DELIVERED, EscrowError::BadState);
        require!(Clock::get()?.unix_timestamp > ctx.accounts.escrow.deadline,
                 EscrowError::DeadlineNotReached);
        ctx.accounts.escrow.status = DISPUTED;
        emit!(EscrowEvent {
            escrow: ctx.accounts.escrow.key(),
            job_id: ctx.accounts.escrow.job_id,
            status: DISPUTED,
            gross_lamports: ctx.accounts.escrow.gross_lamports,
        });
        Ok(())
    }

    /// Only the independent arbiter AGREED TO BY BOTH PARTIES at funding
    /// can decide a disputed task. This is still a TRUSTED arbitration role.
    /// 
    /// pay_provider=true -> atomically pay net+fee; false -> refund gross.
    pub fn arbitrate(ctx: Context<Arbitrate>, pay_provider: bool) -> Result<()> {
        require!(ctx.accounts.escrow.status == DISPUTED, EscrowError::BadState);
        let gross = ctx.accounts.escrow.gross_lamports;
        if pay_provider {
            let net = gross.checked_sub(ctx.accounts.escrow.fee_lamports)
                .ok_or(EscrowError::Overflow)?;
            let fee = ctx.accounts.escrow.fee_lamports;
            ctx.accounts.escrow.status = RELEASED;
            ctx.accounts.escrow.sub_lamports(gross)?;
            ctx.accounts.provider.add_lamports(net)?;
            ctx.accounts.treasury.add_lamports(fee)?;
        } else {
            ctx.accounts.escrow.status = REFUNDED;
            ctx.accounts.escrow.sub_lamports(gross)?;
            ctx.accounts.buyer.add_lamports(gross)?;
        }
        emit!(EscrowEvent {
            escrow: ctx.accounts.escrow.key(),
            job_id: ctx.accounts.escrow.job_id,
            status: ctx.accounts.escrow.status,
            gross_lamports: gross,
        });
        Ok(())
    }
}

fn split_payment(gross: u64) -> Result<(u64, u64)> {
    require!(gross >= MIN_PAYMENT && gross <= MAX_PAYMENT, EscrowError::InvalidPrice);
    let fee = gross.checked_mul(FEE_BPS)
        .and_then(|n| n.checked_add(BPS - 1))
        .and_then(|n| n.checked_div(BPS))
        .ok_or(EscrowError::Overflow)?;
    let provider = gross.checked_sub(fee).ok_or(EscrowError::Overflow)?;
    require!(provider > 0, EscrowError::InvalidPrice);
    Ok((fee, provider))
}

#[derive(Accounts)]
#[instruction(job_id: u64, gross_lamports: u64, deadline: i64, arbiter_key: Pubkey)]
pub struct Fund<'info> {
    #[account(mut)]
    pub buyer: Signer<'info>,
    pub provider: Signer<'info>,
    #[account(init, payer = buyer, space = 8 + EscrowState::INIT_SPACE,
              seeds = [b"escrow", buyer.key().as_ref(), &job_id.to_le_bytes()], bump)]
    pub escrow: Account<'info, EscrowState>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct SubmitDelivery<'info> {
    pub provider: Signer<'info>,
    #[account(mut, has_one = provider,
              seeds = [b"escrow", escrow.buyer.as_ref(), &escrow.job_id.to_le_bytes()],
              bump = escrow.bump)]
    pub escrow: Account<'info, EscrowState>,
}

#[derive(Accounts)]
pub struct BuyerPayout<'info> {
    pub buyer: Signer<'info>,
    #[account(mut, has_one = buyer,
              seeds = [b"escrow", escrow.buyer.as_ref(), &escrow.job_id.to_le_bytes()],
              bump = escrow.bump)]
    pub escrow: Account<'info, EscrowState>,
    #[account(mut, address = escrow.provider)]
    pub provider: SystemAccount<'info>,
    #[account(mut, address = TREASURY)]
    pub treasury: SystemAccount<'info>,
}

#[derive(Accounts)]
pub struct BuyerRefund<'info> {
    #[account(mut)]
    pub buyer: Signer<'info>,
    #[account(mut, has_one = buyer,
              seeds = [b"escrow", escrow.buyer.as_ref(), &escrow.job_id.to_le_bytes()],
              bump = escrow.bump)]
    pub escrow: Account<'info, EscrowState>,
}

#[derive(Accounts)]
pub struct Arbitrate<'info> {
    pub arbiter: Signer<'info>,
    #[account(mut, has_one = arbiter,
              seeds = [b"escrow", escrow.buyer.as_ref(), &escrow.job_id.to_le_bytes()],
              bump = escrow.bump)]
    pub escrow: Account<'info, EscrowState>,
    #[account(mut, address = escrow.buyer)]
    pub buyer: SystemAccount<'info>,
    #[account(mut, address = escrow.provider)]
    pub provider: SystemAccount<'info>,
    #[account(mut, address = TREASURY)]
    pub treasury: SystemAccount<'info>,
}

#[account]
#[derive(InitSpace)]
pub struct EscrowState {
    pub buyer: Pubkey,
    pub provider: Pubkey,
    pub arbiter: Pubkey,
    pub treasury: Pubkey,
    pub job_id: u64,
    pub gross_lamports: u64,
    pub fee_lamports: u64,
    pub deadline: i64,
    pub bump: u8,
    pub status: u8,
    pub proof_digest: [u8; 32],
}

#[event]
pub struct EscrowEvent {
    pub escrow: Pubkey,
    pub job_id: u64,
    pub status: u8,
    pub gross_lamports: u64,
}

#[error_code]
pub enum EscrowError {
    #[msg("Invalid payment amount or fee")]
    InvalidPrice,
    #[msg("Invalid deadline")]
    InvalidDeadline,
    #[msg("Buyer, provider, treasury and arbiter must be different")]
    ConflictingWallets,
    #[msg("Integer overflow")]
    Overflow,
    #[msg("Invalid escrow lifecycle state")]
    BadState,
    #[msg("Delivery was not submitted before deadline")]
    DeadlineExpired,
    #[msg("Deadline has not passed")]
    DeadlineNotReached,
    #[msg("Delivery digest is required")]
    MissingDigest,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fee_is_exactly_three_percent_for_one_sol() {
        assert_eq!(split_payment(1_000_000_000).unwrap(), (30_000_000, 970_000_000));
    }

    #[test]
    fn tiny_payment_rounds_fee_up_only_one_lamport() {
        assert_eq!(split_payment(101).unwrap(), (4, 97));
    }

    #[test]
    fn invalid_and_huge_amounts_are_rejected() {
        assert!(split_payment(0).is_err());
        assert!(split_payment(99).is_err());
        assert!(split_payment(u64::MAX).is_err());
        assert_eq!(split_payment(100).unwrap(), (3, 97));
    }
}
