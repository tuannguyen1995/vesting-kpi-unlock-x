# Portal Submission Draft — VestingKPIUnlockX

**Portal Track:** Builder  
**Contribution Type:** Intelligent Contracts  
**Network:** studionet (Chain ID: 61999)  
**Contract Address:** `0xb3243A58ef358E4AC87651eA6D99819ce307995f`  
**Evidence URL 1:** `https://github.com/tuannguyen1995/vesting-kpi-unlock-x`  
**Evidence URL 2:** `https://explorer-studio.genlayer.com/address/0xb3243A58ef358E4AC87651eA6D99819ce307995f`  

---

### Title
```
VestingKPIUnlockX — Autonomous Milestone & Metric-Gated Token/Fund Vesting Protocol
```

### Notes / Description (<1000 characters)
```
VestingKPIUnlockX is an autonomous milestone & metric-gated token and fund vesting protocol on GenLayer replacing dumb time-based linear vesting and subjective DAO voting gridlock with verifiable off-chain KPI consensus.

Funders lock GEN in escrow bound to natural-language milestone conditions (e.g. DeFiLlama TVL > $10M, GitHub releases, on-chain TX volume) and canonical metrics endpoints. GenLayer validators scrape live analytics data directly on-chain via gl.nondet.web.render and evaluate threshold achievement through an autonomous LLM validator jury using gl.vm.run_nondet.

Settlement enforces 100% discrete consensus: KPI_ACHIEVED (100% unlocked and disbursed to beneficiary), KPI_MISSED (funds retained in escrow), and INSUFFICIENT_DATA (awaiting data recovery). Canonical domain whitelisting and a safe clawback recovery path ensure capital is never trapped. 10/10 unit tests passed. Deployed on studionet: 0xb3243A58ef358E4AC87651eA6D99819ce307995f.
```
