#!/usr/bin/env python3
"""Read-only Cloudflare inventory for Garcar Enterprise.

Requires CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID in the environment.
Makes only GET requests; never changes DNS, Workers, secrets, or Stripe.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
EXPECTED = {
    "Workers": (
        "garcar-payments",
        "garcar-lead-capture",
        "garcar-operator-fabric",
        "garcar-stripe-webhook",
        "garcar-health-monitor",
        "garcar-lead-router",
        "garcar-stripe-poller",
        "garcar-config-bus",
    ),
    "Queues": (
        "stripe-events",
        "stripe-events-dlq",
        "garcar-ops-queue",
        "garcar-notify-queue",
        "garcar-dlq",
    ),
    "D1": ("garcar-payments-db", "garcar-stripe-events"),
}


def get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        API + path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.load(response)
    if not isinstance(data, dict) or data.get("success") is not True:
        raise ValueError("Cloudflare API returned an unsuccessful response")
    return data


def names(data: dict) -> tuple[set[str], bool]:
    records = data.get("result", [])
    if isinstance(records, dict):
        records = next(
            (records[k] for k in ("queues", "databases", "items") if isinstance(records.get(k), list)),
            [],
        )
    if not isinstance(records, list):
        raise ValueError("Unrecognized Cloudflare list response")
    present = {
        name for item in records if isinstance(item, dict)
        for name in (item.get("name"), item.get("id"), item.get("script_name"))
        if isinstance(name, str)
    }
    info = data.get("result_info") or {}
    total_pages = info.get("total_pages", 1) if isinstance(info, dict) else 1
    return present, isinstance(total_pages, int) and total_pages > 1


def main() -> int:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    lines = [
        "# Cloudflare inventory — read-only",
        "",
        "This job never modifies production resources. It checks the selected Cloudflare account only.",
        "",
        "| Resource | Expected names in this account | Result |",
        "|---|---|---|",
    ]
    if not token or not account:
        lines.append("| Credentials | Account ID and scoped API token | MISSING |")
        report(lines)
        print("Missing Cloudflare repository secrets.", file=sys.stderr)
        return 2

    endpoints = {
        "Workers": f"/accounts/{account}/workers/scripts",
        "Queues": f"/accounts/{account}/queues",
        "D1": f"/accounts/{account}/d1/database",
    }
    failures = False
    for kind, path in endpoints.items():
        try:
            found, incomplete = names(get(path, token))
            observed = [name for name in EXPECTED[kind] if name in found]
            absent = [name for name in EXPECTED[kind] if name not in found]
            if incomplete:
                status = "PARTIAL INVENTORY (pagination)"
            else:
                status = "Found: " + (", ".join(observed) if observed else "none of the known names")
                if absent:
                    status += "; not found: " + ", ".join(absent)
            lines.append(f"| {kind} | {', '.join(EXPECTED[kind])} | {status} |")
        except urllib.error.HTTPError as exc:
            failures = True
            lines.append(f"| {kind} | {', '.join(EXPECTED[kind])} | UNVERIFIED: HTTP {exc.code} |")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
            failures = True
            # Never print API response bodies, tokens, or account identifiers.
            lines.append(f"| {kind} | {', '.join(EXPECTED[kind])} | UNVERIFIED ({type(exc).__name__}) |")

    lines.extend([
        "",
        "Known names are drawn from separate Garcar repositories; a missing name is not "
        "proof it is absent from every Cloudflare account.",
        "",
        "DNS routes, Worker runtime health, Stripe webhook signatures, D1 migrations, "
        "and secrets are **not** verified by this inventory.",
    ])
    report(lines)
    if failures:
        print("Cloudflare resource lists could not all be verified. See job summary.", file=sys.stderr)
    return int(failures)


def report(lines: list[str]) -> None:
    summary = "\n".join(lines) + "\n"
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as file:
            file.write(summary)
    else:
        print(summary)


if __name__ == "__main__":
    raise SystemExit(main())
