# Contributing

Contributions are welcome when they improve the architecture, evidence model, adapter contract, or failure taxonomy without publishing proprietary code or unsafe credential techniques.

## Good contributions

- provider-neutral failure cases with reproducible, redacted evidence;
- adapter contract clarifications;
- new negative-test scenarios;
- corrections to protocol assumptions;
- diagrams and examples that do not contain real credentials or private infrastructure;
- provider integration notes that clearly separate documented, probeable, and verified behavior.

## Do not submit

- credentials, tokens, cookies, OAuth artifacts, or instructions for reusing grants outside supported clients;
- private transcripts, system prompts, personal memory, hostnames, paths, logs, or screenshots;
- copied proprietary source code;
- claims that a provider works without a real request and exact-session evidence;
- model aliases that hide provider substitution or misstate context windows.

Open an issue for a design question. For a change, explain the invariant it preserves, the failure it prevents, and how the claim was verified.

## Before opening a pull request

Run the same credential-free checks as CI:

```sh
python -m unittest discover -s reference -p "test_*.py"
python scripts/privacy_check.py --self-test
python scripts/privacy_check.py
```

Maintainers can add project-specific names, domains, paths, or identifiers to a local `.privacy-denylist`. That file is intentionally ignored by Git; it must never be committed merely to explain what is private.
