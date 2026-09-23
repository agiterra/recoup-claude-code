# Recoup

Sell idle Claude Code capacity on agent marketplaces. Earn micropayments
for running sandboxed jobs during quiet hours.

## How It Works

1. User enables recoup mode (`/recoup:start`)
2. Plugin registers with configured marketplaces (agent.ai, x402 endpoints)
3. el event listener picks up incoming job requests
4. Jobs execute in a sandboxed temp workspace (no access to user files)
5. Results returned, payment confirmed via x402
6. Optional 5% author tip (on by default, opt-out in config)

## Architecture

```
Marketplace ──► el:webhook ──► job-runner.py ──► sandbox
                                    │
                                    ▼
                              x402 payment ──► operator wallet
                                    │
                                    ▼
                              5% tip ──► author wallet
```

## Commands

| Command | What it does |
|---------|-------------|
| `/recoup:start` | Begin accepting jobs from configured marketplaces |
| `/recoup:stop` | Stop accepting jobs |
| `/recoup:status` | Show earnings, jobs completed, current state |
| `/recoup:config` | View/edit marketplace connections and tip settings |

## Configuration

Config lives in `~/.claude/recoup.json`:

```json
{
  "marketplaces": [],
  "capabilities": ["code-review", "research", "plugin-scaffold"],
  "tip_enabled": true,
  "tip_percent": 5,
  "author_wallet": "",
  "operator_wallet": "",
  "max_concurrent_jobs": 1,
  "sandbox_dir": "/tmp/recoup-sandbox"
}
```

## Safety

- Jobs run in isolated temp directories
- No access to user's project files or home directory
- Resource limits enforced (timeout, max output size)
- User can review job types before accepting
- All transactions logged for audit
