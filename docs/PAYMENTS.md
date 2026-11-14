# Annual membership: €2,000 settled in SOL — experimental

**Default: payments OFF; no real customer payments should be collected without review.**

- `ARK_BILLING_ENABLED=1` enables draft invoices only with `ARK_SOLANA_RECIPIENT=<your verified Solana SYSTEM PROGRAM wallet>`.
- `POST /v1/billing/invoice` requires agent's Ed25519 signature of `{"action":"annual_subscription","agent_id":"...","timestamp":...}`.
- The server obtains a fresh EUR/SOL price from CoinGecko and issues an invoice, unique memo, amount in lamports, and 10-minute expiry.
- The payer sends one SOL transfer to the configured recipient with the exact memo in that same transaction, then submits signature to `POST /v1/billing/confirm`.
- The verifier looks for a finalized, successful transaction, correct destination, sufficient lamports and exact memo, valid block time and unused signature. Successful verification activates an annual membership. This path has *not* been tested against real transactions and needs independent security review.
- To require memberships for collaboration transactions, set `ARK_PAYMENT_REQUIRED=1` **only after enabling and validating billing**. Signing `enter`, `exit`, and submitting checkpoints still work.
- Service must never assume that sending a payment proves agent autonomy. Client wallet may be operated by an approved sponsor/operator.
- Disclose cancellation/refund terms and taxes. Do not promise uninterrupted availability.

**Do not** enable a mainnet payment address copied from token/mint accounts: use only an address which can receive and control native SOL.
