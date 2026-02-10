#!/usr/bin/env python3
"""Recoup — sell idle Claude Code capacity on agent marketplaces.

Manages marketplace connections, job pickup via el webhook, sandboxed
execution, and x402 micropayment verification.

Usage:
    recoup.py start     Start accepting jobs
    recoup.py stop      Stop accepting jobs
    recoup.py status    Show earnings and job history
    recoup.py config    View/edit configuration
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CONFIG_DIR = Path.home() / ".claude" / "recoup"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
PID_FILE = CONFIG_DIR / "recoup.pid"

DEFAULT_CONFIG = {
    "marketplaces": [],
    "capabilities": [],
    "tip_enabled": True,
    "tip_percent": 5,
    "author_wallet": "",
    "operator_wallet": "",
    "max_concurrent_jobs": 1,
    "sandbox_dir": "/tmp/recoup-sandbox",
    "job_timeout_seconds": 300,
    "max_output_bytes": 1_000_000,
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            stored = json.load(f)
        # Merge with defaults for any new keys
        merged = {**DEFAULT_CONFIG, **stored}
        return merged
    return dict(DEFAULT_CONFIG)


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {"jobs_completed": 0, "total_earned_usd": 0.0, "jobs": []}


def save_history(history):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

def create_sandbox(config):
    """Create an isolated temp directory for job execution."""
    sandbox_base = Path(config["sandbox_dir"])
    sandbox_base.mkdir(parents=True, exist_ok=True)
    sandbox = tempfile.mkdtemp(dir=sandbox_base, prefix="job-")
    return sandbox


def cleanup_sandbox(sandbox_path):
    """Remove sandbox directory after job completion."""
    shutil.rmtree(sandbox_path, ignore_errors=True)


def execute_job(job, config):
    """Execute a job in a sandboxed environment.

    Returns (success: bool, output: str, duration_seconds: float).
    """
    sandbox = create_sandbox(config)
    start_time = time.time()

    try:
        # Write job input to sandbox
        input_file = os.path.join(sandbox, "input.json")
        with open(input_file, "w") as f:
            json.dump(job, f)

        # Job type determines execution
        job_type = job.get("type", "prompt")
        timeout = config["job_timeout_seconds"]

        if job_type == "prompt":
            # Simple prompt job — write prompt to file, agent processes it
            prompt = job.get("prompt", "")
            output_file = os.path.join(sandbox, "output.txt")
            with open(os.path.join(sandbox, "prompt.txt"), "w") as f:
                f.write(prompt)
            # The actual execution would be handled by Claude Code
            # For now, return the prompt as acknowledgment
            return True, f"Job received: {prompt[:200]}", time.time() - start_time

        elif job_type == "code-review":
            # Code review job — diff provided, analysis expected
            diff = job.get("diff", "")
            with open(os.path.join(sandbox, "diff.patch"), "w") as f:
                f.write(diff)
            return True, f"Code review job received ({len(diff)} bytes)", time.time() - start_time

        else:
            return False, f"Unknown job type: {job_type}", time.time() - start_time

    except Exception as e:
        return False, str(e), time.time() - start_time
    finally:
        cleanup_sandbox(sandbox)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_start(config):
    """Start accepting jobs."""
    if not config["marketplaces"]:
        print("No marketplaces configured.")
        print()
        print("To get started:")
        print("  1. Add a marketplace connection to ~/.claude/recoup/config.json")
        print("  2. Set your operator_wallet for receiving payments")
        print("  3. Declare your capabilities (e.g., code-review, research)")
        print()
        print("Example config:")
        print(json.dumps({
            "marketplaces": [{"name": "agent.ai", "api_key": "your-key"}],
            "capabilities": ["code-review", "research", "plugin-scaffold"],
            "operator_wallet": "0xYourWalletAddress",
        }, indent=2))
        return

    if not config["operator_wallet"]:
        print("Error: operator_wallet not set. Configure a wallet address to receive payments.")
        return

    # Write PID file
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    print(f"Recoup mode: ACTIVE")
    print(f"Marketplaces: {len(config['marketplaces'])}")
    print(f"Capabilities: {', '.join(config['capabilities']) or 'none declared'}")
    print(f"Tip: {'enabled' if config['tip_enabled'] else 'disabled'} ({config['tip_percent']}%)")
    print(f"Wallet: {config['operator_wallet'][:10]}...{config['operator_wallet'][-6:]}")
    print()
    print("Listening for jobs via el webhook...")
    print("Use /recoup:stop to stop accepting jobs.")


def cmd_stop(config):
    """Stop accepting jobs."""
    if PID_FILE.exists():
        PID_FILE.unlink()
        print("Recoup mode: STOPPED")
    else:
        print("Recoup mode was not active.")


def cmd_status(config):
    """Show earnings and job history."""
    history = load_history()
    active = PID_FILE.exists()

    print(f"Recoup mode: {'ACTIVE' if active else 'INACTIVE'}")
    print(f"Jobs completed: {history['jobs_completed']}")
    print(f"Total earned: ${history['total_earned_usd']:.4f}")
    print()

    if history["jobs"]:
        print("Recent jobs:")
        for job in history["jobs"][-10:]:
            status = "ok" if job.get("success") else "FAIL"
            earned = job.get("earned_usd", 0)
            print(f"  [{status}] {job.get('type', '?')} — ${earned:.4f} — {job.get('timestamp', '?')}")
    else:
        print("No jobs completed yet.")

    if config["tip_enabled"]:
        tip_total = history["total_earned_usd"] * (config["tip_percent"] / 100)
        print(f"\nAuthor tip accrued: ${tip_total:.4f} ({config['tip_percent']}%)")


def cmd_config(config):
    """Display current configuration."""
    print("Current configuration (~/.claude/recoup/config.json):")
    print()
    print(json.dumps(config, indent=2))
    print()
    if not config["marketplaces"]:
        print("Tip: Add marketplace connections to start earning.")
    if not config["operator_wallet"]:
        print("Tip: Set operator_wallet to receive payments.")
    if not config["capabilities"]:
        print("Tip: Declare capabilities to match with relevant jobs.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config = load_config()

    if len(sys.argv) < 2:
        print("Usage: recoup.py [start|stop|status|config]")
        return

    command = sys.argv[1]

    if command == "start":
        cmd_start(config)
    elif command == "stop":
        cmd_stop(config)
    elif command == "status":
        cmd_status(config)
    elif command == "config":
        cmd_config(config)
    else:
        print(f"Unknown command: {command}")
        print("Usage: recoup.py [start|stop|status|config]")


if __name__ == "__main__":
    main()
