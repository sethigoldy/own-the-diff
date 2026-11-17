# Own the Diff

[![CI](https://github.com/sethigoldy/own-the-diff/actions/workflows/ci.yml/badge.svg)](https://github.com/sethigoldy/own-the-diff/actions/workflows/ci.yml) · [Apache 2.0](LICENSE) · [Review guide](docs/review-guide.md) · [CLI reference](docs/cli.md)

Review a feature across Git repositories before you sign off on AI-generated code. Open the producer and consumer diffs side by side, record what you checked, and see which decisions need another look after the next edit. The browser and the `cor` CLI share one local review.

In the working demo, a Python job service returns `{"job_id": job.id}`. Its unit test passes. In a second repository, the TypeScript portal reads `result.jobId`. A successful retry leaves the operator without a job identifier. Open **Retry response field** to see the two lines together and request the fix.

![The demo review shows the Python response and TypeScript caller side by side, with the field mismatch linked to both diffs.](docs/images/retry-decision.png)

## Try the demo

You need Git and Python 3.9 or later. The checkout includes the built web app. The demo runs locally without an account, model, or Node installation.

```sh
git clone https://github.com/sethigoldy/own-the-diff.git
cd own-the-diff
python3 -m cor demo
python3 -m cor web --session "Retry failed jobs"
```

Open **Inspect both sides** on the retry relationship. Request changes in the browser, then run `python3 -m cor history --session "Retry failed jobs"` in another terminal to see the same decision. The demo command prints both example directories so you can edit the portal, refresh the capture, and inspect what changed.

For a browser-only start, run `python3 -m cor web` and choose **Explore the working demo** or **New review**. On macOS you can also open **Code Ownership Review.app** from the checkout. Keep the launcher beside the source. To make `cor` available outside the checkout, run `uv tool install .` or `pipx install .`.

## Review your own feature

1. Choose **New review**. Describe what the feature should do and add the local Git repositories it touches. Give each repository its own base and target.
2. Connect the producer path and consumer path for each interface you want to check. Reuse a producer for multiple consumers. Review suggested HTTP connections in **Overview**.
3. Inspect the paired diffs and the remaining changes in **Decisions** and **Files**. Approve, defer, or request changes against the frozen evidence.
4. After an edit, refresh. **History** shows which decisions carried forward. **Handoff** compares the capture with live Git and exports a Markdown summary or JSON ledger.

Prefer a terminal? Start with the [example project file](examples/review.json) and follow the [CLI walkthrough](docs/cli.md). You can switch clients at any point.

## Documentation

| If you want to… | Start here |
| --- | --- |
| Fix the demo mismatch, set up a multi-repository review, or understand a blocked handoff | [Review guide](docs/review-guide.md) |
| Configure repositories, run trusted checks, import findings, or automate verification | [CLI reference](docs/cli.md) |
| Understand what is stored, exported, or sent to a local model | [Data handling and security](SECURITY.md) |
| Work on Git capture, the decision ledger, or the browser | [Architecture](ARCHITECTURE.md) and [contributor guide](CONTRIBUTING.md) |
| Review the longer-term design and pilot acceptance criteria | [Product specification](product-spec.md) |

The current release is a single-user local workspace. It reads local Git changes, keeps decisions in SQLite, and exports reports you can attach to a pull request yourself. Optional Ollama analysis can add findings. A human records approvals.

## License

Own the Diff is licensed under [Apache 2.0](LICENSE). The bundled browser dependencies have their own [license notices](THIRD_PARTY_NOTICES.txt).
