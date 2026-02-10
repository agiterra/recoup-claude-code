---
description: Start selling idle capacity on agent marketplaces. Accepts sandboxed jobs and earns micropayments.
argument-hint: [start|stop|status|config]
allowed-tools: Bash, Read, Write
---

# Recoup Mode

Manage idle capacity selling.

## Arguments

- `start` — Begin accepting jobs from configured marketplaces
- `stop` — Stop accepting jobs gracefully
- `status` — Show earnings, jobs completed, active connections
- `config` — View or edit configuration

## Start

```
Bash(command="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/recoup.py start")
```

Read the output. If marketplaces aren't configured, guide the user through
setup: marketplace registration, wallet address, capability declaration.

## Stop

```
Bash(command="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/recoup.py stop")
```

## Status

```
Bash(command="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/recoup.py status")
```

Show earnings summary, jobs completed, and current connection state.

## Config

```
Bash(command="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/recoup.py config")
```

Display current configuration. User can modify settings interactively.
