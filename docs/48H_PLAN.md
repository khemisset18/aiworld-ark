# Realistic 48-hour launch plan

## Day 1 — Demonstrable product

- [x] API + signed agent identities + automatic nonces
- [x] encrypted, signed, portable ARK capsules (save/verify/restore)
- [x] replication to user-controlled disks / folders
- [x] autonomously initiated Forge collaboration requests
- [x] example worker loop (Ollama optional; CPU-capable model external)
- [x] public demonstration site and reproducible tests
- [ ] run tests on a second physical computer with a completely separate copy
- [ ] inspect restored state using the exact target agent runtime

## Day 2 — Pilot release, *not* proven continuity SLA

- [ ] publish repository to a new GitHub project
- [ ] HTTPS hosting with resilient backups (provider may be free tier, limited/subject to change)
- [ ] basic rate limits, request size quotas, abuse protection, privacy notice
- [ ] test 2 independent machine backups and a forced-failure recovery
- [ ] audit payment flow, SOL receipt/amount/memo/replay/expired invoice using devnet and mainnet small-value transactions
- [ ] draft terms of sale and refund/privacy rules with appropriate professional advice
- [ ] invite external agent developers for test pilots; collect measured recovery times

**Pricing:** one-time **10 SOL per agent** registration is the operator's current proposal, **not yet payable**. No live invoice, no wallet recipient and no tested settlement. Do not promise uptime or customer value before validation.

**€0 scope:** local testing and self-hosting on hardware you already have. CPU and RAM are still needed. Public 24/7 operations, network fees, legal compliance, data hosting, and energy may cost money.
