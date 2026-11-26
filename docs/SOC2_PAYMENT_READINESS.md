# Payment service: SOC 2 readiness remediation

Status: **Proposed controls; not a SOC 2 report or attestation**. Owner must review this change and retain CI evidence after merge.

## Changes proposed in this branch

1. Remove `.github/workflows/deploy-payments.yml`. This workflow printed successful deployment and payment-endpoint assertions without calling a deployment API or executing endpoint tests. Its green status was not evidence of an actual deployment. The separate manual `.github/workflows/deploy.yml` remains, subject to real environment approval and successful post-deployment health checks. **Do not infer that GitHub environment approval rules are configured merely from the YAML `environment: production` declaration.**
2. Remove `.github/workflows/keyless-secret-rotation.yml`. The former implementation generated a private signing key in ephemeral CI and discarded it; changing Stripe webhook event subscriptions does not rotate the Stripe webhook signing secret. Its push-triggered side effects and completion messages were not reliable rotation evidence. Keep live Stripe credentials and endpoints unchanged while designing an audited, dual-secret cutover and rollback process.
3. Make `.github/workflows/db-backup.yml` fail if database or encryption credentials are absent, instead of succeeding while skipping the backup. Require successful `pg_dump`, archive validation, decryption verification, and upload of encrypted artifacts. **Archive validation is not a successful restore drill**. GitHub Actions artifact retention is 30 days; this does not establish backup retention, immutability, offsite resilience, or a tested RPO/RTO.

## Required follow-up verification (not completed by this PR)

- [ ] Confirm the actual production payment service, custom domain and deployed commit; prove a deployed endpoint responds correctly.
- [ ] Configure GitHub production environment required reviewers and deployment branch restrictions; retrieve a screenshot or API evidence. Manual workflow alone is insufficient.
- [ ] Require passing CI, dependency/security scanning, and owner review on protected default branch. Verify branch protection/ruleset settings via GitHub administration.
- [ ] Prove live Stripe signature validation on raw request bytes, replay/idempotency controls, least-privilege secret access, and alerting on rejected events.
- [ ] Prove payment and customer records are never logged or committed with secrets or unnecessary personal data.
- [ ] Configure and test a separately isolated encrypted backup location, periodic real restore to an isolated database, documented recovery objectives, and backup alerting.
- [ ] Implement actual webhook-signing secret rotation with overlap, verification, and rollback; evidence success from Stripe and the service, not a log statement.
- [ ] Preserve evidence of CI checks, reviewed pull requests, access reviews, incident handling, and production releases for the auditor.

**Evidence rule:** An output log is evidence of the command that ran, not proof of an external action unless the target service independently confirms the result. Do not mark a control effective on an unverified or skipped run.
