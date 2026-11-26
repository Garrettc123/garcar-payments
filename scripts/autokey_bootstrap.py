#!/usr/bin/env python3
"""Retired Railway AutoKey pathway.

The former script printed secret-bearing CLI arguments, deleted existing
Stripe webhook endpoints, recreated signing secrets and reused unrelated
Price IDs. It is intentionally non-operational to prevent lost payment
evidence or an accidental legacy-account rebind.

Existing Stripe objects, deployments and historical records are unchanged.
Use the reviewed Cloudflare AutoKey path after confirming the active account,
D1 persistence, queues, credentials and a verified staging delivery.
"""
from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "BLOCKED: legacy Railway AutoKey is retired. "
        "Use scripts/autokey_bootstrap_cf.py only after active-account "
        "and durable-Cloudflare preflight checks succeed."
    )


if __name__ == "__main__":
    main()
