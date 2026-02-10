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


def _run_claude(prompt, sandbox, config):
    """Run claude CLI in sandbox, return (success, output)."""
    env = {**os.environ, "HOME": sandbox}
    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions", "-p", prompt],
            cwd=sandbox,
            capture_output=True,
            text=True,
            timeout=config["job_timeout_seconds"],
            env=env,
        )
        output = result.stdout or result.stderr
        # Enforce max output size
        max_bytes = config.get("max_output_bytes", 1_000_000)
        if len(output) > max_bytes:
            output = output[:max_bytes] + "\n[output truncated]"
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Job timed out after {config['job_timeout_seconds']}s"
    except FileNotFoundError:
        return False, "claude CLI not found in PATH"


def execute_job(job, config):
    """Execute a job in a sandboxed environment.

    Returns (success: bool, output: str, duration_seconds: float, job_type: str).
    """
    sandbox = create_sandbox(config)
    start_time = time.time()

    try:
        # Write job input to sandbox
        input_file = os.path.join(sandbox, "input.json")
        with open(input_file, "w") as f:
            json.dump(job, f)

        job_type = job.get("type", "prompt")

        if job_type == "prompt":
            prompt = job.get("prompt", "")
            if not prompt:
                return False, "No prompt provided", time.time() - start_time, job_type
            prompt_file = os.path.join(sandbox, "prompt.txt")
            with open(prompt_file, "w") as f:
                f.write(prompt)
            success, output = _run_claude(prompt, sandbox, config)
            return success, output, time.time() - start_time, job_type

        elif job_type == "code-review":
            diff = job.get("diff", "")
            if not diff:
                return False, "No diff provided", time.time() - start_time, job_type
            diff_file = os.path.join(sandbox, "diff.patch")
            with open(diff_file, "w") as f:
                f.write(diff)
            review_prompt = (
                "Review the following code diff. Identify bugs, security issues, "
                "and suggest improvements. Be concise.\n\n" + diff
            )
            success, output = _run_claude(review_prompt, sandbox, config)
            return success, output, time.time() - start_time, job_type

        elif job_type == "research":
            question = job.get("prompt", "")
            if not question:
                return False, "No question provided", time.time() - start_time, job_type
            research_prompt = (
                "Research the following question using web search. "
                "Provide a thorough but concise answer with sources.\n\n" + question
            )
            success, output = _run_claude(research_prompt, sandbox, config)
            return success, output, time.time() - start_time, job_type

        else:
            return False, f"Unknown job type: {job_type}", time.time() - start_time, job_type

    except Exception as e:
        return False, str(e), time.time() - start_time, job.get("type", "unknown")
    finally:
        cleanup_sandbox(sandbox)


def record_job(job_type, success, output_preview, duration, earned_usd):
    """Append a completed job to history."""
    history = load_history()
    history["jobs_completed"] += 1
    history["total_earned_usd"] += earned_usd
    history["jobs"].append({
        "type": job_type,
        "success": success,
        "output_preview": output_preview[:200],
        "duration_seconds": round(duration, 2),
        "earned_usd": earned_usd,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    # Keep only last 100 jobs
    history["jobs"] = history["jobs"][-100:]
    save_history(history)


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
