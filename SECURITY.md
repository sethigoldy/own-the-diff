# Security and data handling

## Report a vulnerability

Use GitHub's [private vulnerability reporting form](https://github.com/sethigoldy/own-the-diff/security/advisories/new) for security-sensitive reports. Include the version or Git commit, affected operation, expected behavior, and what you observed. Use synthetic repositories for examples. For a regular bug, open a [public issue](https://github.com/sethigoldy/own-the-diff/issues/new/choose).

## What stays on your machine

The browser connects to a Python service bound to loopback. The CLI talks directly to the same review engine. Both store captures, review decisions, findings, and check results in the workspace under `~/.local/share/code-ownership-review` by default. Set `COR_HOME` to choose another directory.

A capture can contain source from the repositories you selected, including untracked files if enabled. Anyone who can read the workspace or its backups may be able to read that evidence. Keep the workspace outside shared or synced folders when reviewing private work. A new installation does not need a GitHub token or model API key.

## What can leave the workspace

| Operation | Data involved |
| --- | --- |
| Review in the browser or CLI | Frozen local diffs, file context, decisions, and findings. The browser serves its scripts and styles locally. |
| Optional Ollama analysis | The local adapter sends a bounded evidence packet to the model on loopback port 11434. Check how your chosen model and service are configured. |
| Export or independent reviewer packet | Markdown can include objectives, paths, decisions, and findings. JSON can also include patches, test output, and history. Redaction removes known sensitive file contents and detected secret lines on a best-effort basis. Inspect generated files before sharing. |
| Trusted test command | The command runs in a disposable copy under your OS account. It can access files, credentials, or the network wherever that account has permission. Only run code and commands you trust. |

Human-entered text can contain private information. Review objectives, explanations, check output, and filenames before including an export in a public pull request. Deleting a review removes its local database history. Delete exported copies, backups, or demo checkouts separately when you no longer need them.
