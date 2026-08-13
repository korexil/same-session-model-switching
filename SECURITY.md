# Security policy

This repository contains architecture documentation and a credential-free control-plane reference, not a deployable inference service. Please do not publish credentials, private endpoints, OAuth artifacts, personal transcripts, or production logs in issues or pull requests.

If you find sensitive information in the repository, report it privately to the repository owner through GitHub's private vulnerability reporting feature when available. Include the affected path and commit, but do not include live secrets in the report. Revoke exposed credentials before treating repository cleanup as complete.

The repository runs `scripts/privacy_check.py` in CI. It detects common secret shapes, personal absolute paths, public IP addresses, broken local documentation links, and an optional maintainer denylist. This is defense in depth, not a replacement for credential revocation or GitHub secret scanning.
