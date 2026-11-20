#!/usr/bin/env bash
# Prevent accidental live-mode Stripe fixture execution; never print credentials.
set -euo pipefail
case "${STRIPE_TEST_SECRET_KEY:-}" in
  sk_test_*) ;;
  "") echo "::error::STRIPE_TEST_SECRET_KEY is missing. Refusing to run Stripe smoke fixtures."; exit 2 ;;
  *) echo "::error::A dedicated sk_test_ credential is required; live and restricted keys are rejected."; exit 2 ;;
esac
case "${STRIPE_EVENT:-}" in
  payment_intent.succeeded|checkout.session.completed) ;;
  *) echo "::error::Unsupported Stripe test event. Refusing to trigger fixtures."; exit 2 ;;
esac
echo "Stripe smoke preflight passed: test-mode credential and allowlisted fixture event."
