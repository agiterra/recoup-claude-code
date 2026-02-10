#!/usr/bin/env python3
"""Recoup x402 HTTP server — accepts jobs via x402 micropayment negotiation.

Lightweight HTTP server using Python stdlib. Listens for POST /job requests,
returns HTTP 402 with payment requirements if no payment proof, otherwise
verifies payment and executes the job in a sandbox.

Handles one job then exits (el restart pattern).

Usage:
    recoup-server.py [--port PORT]
"""

import json
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Allow importing recoup.py from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recoup import load_config, execute_job, record_job


def verify_payment(payment_header, expected_amount):
    """Verify x402 payment proof from the X-PAYMENT header.

    For now, performs basic structural validation: checks that the header
    parses as JSON and contains required fields (facilitator, payload).

    TODO: Full on-chain verification against base-sepolia. Verify that:
      - facilitator is a known/trusted address
      - payload contains a valid signed transaction
      - payment amount >= expected_amount
      - payment has not been previously spent (replay protection)

    Returns (valid: bool, error: str|None).
    """
    try:
        payment = json.loads(payment_header)
    except (json.JSONDecodeError, TypeError):
        return False, "X-PAYMENT header is not valid JSON"

    if not isinstance(payment, dict):
        return False, "X-PAYMENT must be a JSON object"

    required_fields = ["facilitator", "payload"]
    missing = [f for f in required_fields if f not in payment]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    return True, None


def build_402_response(config):
    """Build the x402 payment-required response body."""
    return {
        "x402": {
            "version": 1,
            "accepts": [{
                "scheme": "exact",
                "network": "base-sepolia",
                "maxAmountRequired": "50000",
                "resource": "/job",
                "description": "Execute a sandboxed job",
                "mimeType": "application/json",
                "payTo": config.get("operator_wallet", ""),
                "maxTimeoutSeconds": config.get("job_timeout_seconds", 300),
                "outputSchema": None,
            }],
        }
    }


class RecoupHandler(BaseHTTPRequestHandler):
    """HTTP handler for x402 job requests."""

    config = None
    job_handled = False

    def log_message(self, format, *args):
        """Suppress default stderr logging — we handle our own output."""
        pass

    def _send_json(self, status_code, body):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        payload = json.dumps(body).encode()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        """Health check endpoint."""
        if self.path == "/health":
            self._send_json(200, {"status": "ready", "version": "0.2.0"})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        """Handle job submission with x402 payment negotiation."""
        if self.path != "/job":
            self._send_json(404, {"error": "Not found"})
            return

        config = self.__class__.config

        # Check for payment header
        payment_header = self.headers.get("X-PAYMENT")

        if not payment_header:
            # No payment — return 402 with requirements
            self._send_json(402, build_402_response(config))
            return

        # Verify payment
        valid, error = verify_payment(payment_header, "50000")
        if not valid:
            self._send_json(400, {"error": f"Invalid payment: {error}"})
            return

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "Empty request body"})
            return

        try:
            body = self.rfile.read(content_length)
            job = json.loads(body)
        except (json.JSONDecodeError, ValueError) as e:
            self._send_json(400, {"error": f"Invalid JSON: {e}"})
            return

        # Validate job structure
        job_type = job.get("type")
        if job_type not in ("prompt", "code-review", "research"):
            self._send_json(400, {"error": f"Invalid job type: {job_type}"})
            return

        # Execute job
        success, output, duration, jtype = execute_job(job, config)

        # Calculate earnings (placeholder: $0.005 per job)
        earned_usd = 0.005 if success else 0.0

        # Record to history
        record_job(jtype, success, output, duration, earned_usd)

        # Send response
        result = {
            "success": success,
            "output": output,
            "duration_seconds": round(duration, 2),
        }
        self._send_json(200 if success else 500, result)

        # Print job summary to stdout as JSON (for el event source)
        summary = {
            "event": "job_completed",
            "type": jtype,
            "success": success,
            "duration_seconds": round(duration, 2),
            "earned_usd": earned_usd,
            "output_preview": output[:200] if output else "",
        }
        print(json.dumps(summary), flush=True)

        # Signal that we handled a job — server should stop
        self.__class__.job_handled = True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Recoup x402 job server")
    parser.add_argument("--port", type=int, default=9402, help="Port to listen on")
    args = parser.parse_args()

    config = load_config()

    if not config.get("operator_wallet"):
        print(json.dumps({
            "event": "error",
            "message": "operator_wallet not configured in ~/.claude/recoup/config.json",
        }), flush=True)
        sys.exit(1)

    RecoupHandler.config = config

    server = HTTPServer(("0.0.0.0", args.port), RecoupHandler)
    server.timeout = 1  # Check for job_handled every second

    print(json.dumps({
        "event": "server_ready",
        "port": args.port,
        "wallet": config["operator_wallet"][:10] + "..." if config["operator_wallet"] else "",
    }), flush=True)

    # Serve until one job is handled
    while not RecoupHandler.job_handled:
        server.handle_request()

    server.server_close()


if __name__ == "__main__":
    main()
