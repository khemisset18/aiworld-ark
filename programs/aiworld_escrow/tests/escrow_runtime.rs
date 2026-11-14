#![cfg(feature = "runtime-tests")]
// Real instruction execution in an in-process Solana bank. NOT a Devnet audit.
// Requires: cargo test --manifest-path programs/aiworld_escrow/Cargo.toml
//            --features runtime-tests --test escrow_runtime
use anchor_lang::{AccountDeserialize, InstructionData, ToAccountMetas};
use aiworld_escrow::{self as escrow_program, EscrowState, TREASURY};
use solana_program_test::{processor, ProgramTest, ProgramTestContext, ProgramTestBanksClientExt};
use solana_sdk::{
    account::Account,
    account_info::AccountInfo,
    clock::Clock,
    entrypoint::ProgramResult,
    instruction::Instruction,
    pubkey::Pubkey,
    signature::{Keypair, Signer},
    system_program,
    transaction::Transaction,
};

// Anchor's entrypoint ties the slice and AccountInfo lifetimes together;
// ProgramTest's generic processor doesn't. A leaked short slice is safe within
// these finite-process integration tests, never compiled in production.
fn native_entry(program_id: &Pubkey, infos: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let infos = Box::leak(Box::new(infos.to_vec()));
    escrow_program::entry(program_id, infos, data)
}

const GROSS: u64 = 1_000_000_000;
const FEE: u64 = 30_000_000;
const NET: u64 = 970_000_000;
const JOB: u64 = 1024;

struct Scenario {
    ctx: ProgramTestContext,
    buyer: Keypair,
    provider: Keypair,
    arbiter: Keypair,
    imposter: Keypair,
    escrow: Pubkey,
    deadline: i64,
}

fn system_account(lamports: u64) -> Account {
    Account { lamports, data: vec![], owner: system_program::id(),
              executable: false, rent_epoch: 0 }
}

async fn start() -> Scenario {
    let buyer = Keypair::new();
    let provider = Keypair::new();
    let arbiter = Keypair::new();
    let imposter = Keypair::new();
    let mut pt = ProgramTest::new("aiworld_escrow", escrow_program::id(),
                                   processor!(native_entry));
    pt.add_account(buyer.pubkey(), system_account(8_000_000_000));
    pt.add_account(provider.pubkey(), system_account(1_000_000));
    pt.add_account(arbiter.pubkey(), system_account(1_000_000));
    pt.add_account(imposter.pubkey(), system_account(1_000_000));
    pt.add_account(TREASURY, system_account(1_000_000));
    let mut ctx = pt.start_with_context().await;
    let clock: Clock = ctx.banks_client.get_sysvar().await.unwrap();
    let deadline = clock.unix_timestamp + 1800;
    let (escrow, _) = Pubkey::find_program_address(
        &[b"escrow", buyer.pubkey().as_ref(), &JOB.to_le_bytes()],
        &escrow_program::id());
    Scenario {ctx, buyer, provider, arbiter, imposter, escrow, deadline}
}

fn instruction<A: ToAccountMetas, D: InstructionData>(accounts: A, data: D) -> Instruction {
    Instruction { program_id: escrow_program::id(),
                  accounts: accounts.to_account_metas(None),
                  data: data.data() }
}

async fn send(ctx: &mut ProgramTestContext, ix: Instruction,
              other_signers: &[&Keypair]) -> Result<(), String> {
    let mut signers: Vec<&dyn Signer> = vec![&ctx.payer];
    for signer in other_signers { signers.push(*signer); }
    let blockhash = ctx.banks_client.get_latest_blockhash().await
        .map_err(|e| e.to_string())?;
    let tx = Transaction::new_signed_with_payer(&[ix],
        Some(&ctx.payer.pubkey()), &signers, blockhash);
    ctx.banks_client.process_transaction(tx).await
        .map_err(|e| e.to_string())
}

fn fund_ix(s: &Scenario, provider: Pubkey) -> Instruction {
    instruction(escrow_program::accounts::Fund {
        buyer: s.buyer.pubkey(), provider, escrow: s.escrow,
        system_program: system_program::id(),
    }, escrow_program::instruction::Fund {
        job_id: JOB, gross_lamports: GROSS, deadline: s.deadline,
        arbiter_key: s.arbiter.pubkey(),
    })
}
async fn fund(s: &mut Scenario) {
    let ix = fund_ix(s, s.provider.pubkey());
    send(&mut s.ctx, ix, &[&s.buyer, &s.provider]).await
        .expect("buyer and provider must both authorize funding");
}

fn deliver_ix(s: &Scenario, provider: Pubkey) -> Instruction {
    instruction(escrow_program::accounts::SubmitDelivery {
        provider, escrow: s.escrow,
    }, escrow_program::instruction::SubmitDelivery { digest: [5u8; 32] })
}
async fn deliver(s: &mut Scenario) {
    let ix = deliver_ix(s, s.provider.pubkey());
    send(&mut s.ctx, ix, &[&s.provider]).await.unwrap();
}

async fn balance(s: &mut Scenario, who: Pubkey) -> u64 {
    s.ctx.banks_client.get_account(who).await.unwrap().unwrap().lamports
}
async fn state(s: &mut Scenario) -> EscrowState {
    let a = s.ctx.banks_client.get_account(s.escrow).await.unwrap().unwrap();
    EscrowState::try_deserialize(&mut a.data.as_slice()).unwrap()
}
fn accept_ix(s: &Scenario, buyer: Pubkey) -> Instruction {
    instruction(escrow_program::accounts::BuyerPayout {
        buyer, escrow: s.escrow, provider: s.provider.pubkey(),
        treasury: TREASURY,
    }, escrow_program::instruction::AcceptDelivery {})
}
fn refund_ix(s: &Scenario) -> Instruction {
    instruction(escrow_program::accounts::BuyerRefund {
        buyer: s.buyer.pubkey(), escrow: s.escrow,
    }, escrow_program::instruction::RefundUndelivered {})
}
fn joint_ix(s: &Scenario, provider: Pubkey, pay_provider: bool) -> Instruction {
    instruction(escrow_program::accounts::JointSettlement {
        buyer: s.buyer.pubkey(), provider, escrow: s.escrow,
        treasury: TREASURY,
    }, escrow_program::instruction::SettleByAgreement { pay_provider })
}

#[tokio::test]
async fn funded_job_pays_exactly_97_3_after_delivery_and_buyer_acceptance() {
    let mut s = start().await;
    let provider_address = s.provider.pubkey();
    let buyer_address = s.buyer.pubkey();
    let escrow_address = s.escrow;
    let before_provider = balance(&mut s, provider_address).await;
    let before_treasury = balance(&mut s, TREASURY).await;
    fund(&mut s).await;
    assert_eq!(state(&mut s).await.status, escrow_program::FUNDED);
    let pda_before = balance(&mut s, escrow_address).await;
    assert!(pda_before > GROSS); // holds both user funds and separate rent
    let unauthorized = deliver_ix(&s, s.imposter.pubkey());
    assert!(send(&mut s.ctx, unauthorized, &[&s.imposter]).await.is_err());
    deliver(&mut s).await;
    assert_eq!(state(&mut s).await.status, escrow_program::DELIVERED);
    let fake_accept = accept_ix(&s, s.imposter.pubkey());
    assert!(send(&mut s.ctx, fake_accept, &[&s.imposter]).await.is_err());
    let accept = accept_ix(&s, s.buyer.pubkey());
    send(&mut s.ctx, accept, &[&s.buyer]).await.unwrap();
    assert_eq!(balance(&mut s, provider_address).await - before_provider, NET);
    assert_eq!(balance(&mut s, TREASURY).await - before_treasury, FEE);
    assert_eq!(balance(&mut s, escrow_address).await, pda_before - GROSS);
    assert_eq!(state(&mut s).await.status, escrow_program::RELEASED);
    let repeat = accept_ix(&s, s.buyer.pubkey());
    assert!(send(&mut s.ctx, repeat, &[&s.buyer]).await.is_err());
}

#[tokio::test]
async fn undelivered_job_refunds_full_gross_without_platform_fee() {
    let mut s = start().await;
    let provider_address = s.provider.pubkey();
    let buyer_address = s.buyer.pubkey();
    let escrow_address = s.escrow;
    let before_treasury = balance(&mut s, TREASURY).await;
    fund(&mut s).await;
    let before_refund = balance(&mut s, buyer_address).await;
    let early = refund_ix(&s);
    assert!(send(&mut s.ctx, early, &[&s.buyer]).await.is_err());
    let mut clock: Clock = s.ctx.banks_client.get_sysvar().await.unwrap();
    clock.unix_timestamp = s.deadline + 1;
    s.ctx.set_sysvar(&clock);
    let refund = refund_ix(&s);
    send(&mut s.ctx, refund, &[&s.buyer]).await.unwrap();
    assert_eq!(balance(&mut s, buyer_address).await - before_refund, GROSS);
    assert_eq!(balance(&mut s, TREASURY).await, before_treasury);
    assert_eq!(state(&mut s).await.status, escrow_program::REFUNDED);
    let duplicate = refund_ix(&s);
    assert!(send(&mut s.ctx, duplicate, &[&s.buyer]).await.is_err());
}

#[tokio::test]
async fn dispute_requires_the_named_arbitrator_and_can_refund() {
    let mut s = start().await;
    let provider_address = s.provider.pubkey();
    let buyer_address = s.buyer.pubkey();
    let escrow_address = s.escrow;
    fund(&mut s).await;
    deliver(&mut s).await;
    let dispute = instruction(escrow_program::accounts::BuyerRefund {
        buyer: s.buyer.pubkey(), escrow: s.escrow,
    }, escrow_program::instruction::OpenDispute {});
    send(&mut s.ctx, dispute, &[&s.buyer]).await.unwrap();
    let before_buyer = balance(&mut s, buyer_address).await;
    let before_treasury = balance(&mut s, TREASURY).await;
    let fake = instruction(escrow_program::accounts::Arbitrate {
        arbiter: s.imposter.pubkey(), escrow: s.escrow,
        buyer: s.buyer.pubkey(), provider: s.provider.pubkey(), treasury: TREASURY,
    }, escrow_program::instruction::Arbitrate {pay_provider: false});
    assert!(send(&mut s.ctx, fake, &[&s.imposter]).await.is_err());
    let valid = instruction(escrow_program::accounts::Arbitrate {
        arbiter: s.arbiter.pubkey(), escrow: s.escrow,
        buyer: s.buyer.pubkey(), provider: s.provider.pubkey(), treasury: TREASURY,
    }, escrow_program::instruction::Arbitrate {pay_provider: false});
    send(&mut s.ctx, valid, &[&s.arbiter]).await.unwrap();
    assert_eq!(balance(&mut s, buyer_address).await - before_buyer, GROSS);
    assert_eq!(balance(&mut s, TREASURY).await, before_treasury);
    assert_eq!(state(&mut s).await.status, escrow_program::REFUNDED);
}

#[tokio::test]
async fn joint_settlement_requires_original_buyer_and_provider_signatures() {
    let mut s = start().await;
    let provider_address = s.provider.pubkey();
    let buyer_address = s.buyer.pubkey();
    let escrow_address = s.escrow;
    fund(&mut s).await;
    let wrong = joint_ix(&s, s.imposter.pubkey(), false);
    assert!(send(&mut s.ctx, wrong, &[&s.buyer, &s.imposter]).await.is_err());
    let before_buyer = balance(&mut s, buyer_address).await;
    let before_treasury = balance(&mut s, TREASURY).await;
    let mutual_cancel = joint_ix(&s, s.provider.pubkey(), false);
    send(&mut s.ctx, mutual_cancel, &[&s.buyer, &s.provider]).await.unwrap();
    assert_eq!(balance(&mut s, buyer_address).await - before_buyer, GROSS);
    assert_eq!(balance(&mut s, TREASURY).await, before_treasury);
    assert_eq!(state(&mut s).await.status, escrow_program::REFUNDED);
}
