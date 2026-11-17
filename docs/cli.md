# CLI reference

From a checkout use `python3 -m cor`. After `uv tool install .` or `pipx install .`, the same commands are available as `cor`. Use `cor COMMAND --help` for all arguments.

## Start a review

Copy [review.json](../examples/review.json) next to your `job-manager/` and `portal/` checkouts, or edit its aliases, paths, criteria, and relationships for your feature. Repository paths resolve relative to the JSON file. Each contract refers to those aliases and uses paths relative to the corresponding repository root.

```sh
cor init --config review.json
cor list
```

Copy the review ID from the output. Replace `REVIEW_ID`, `UNIT_ID`, and other uppercase placeholders below with values from your review. A unique ID prefix or an exact title also works. With one saved review you can omit `--session`.

## Inspect, decide, refresh

```sh
cor status --session REVIEW_ID
cor inventory --session REVIEW_ID --patch
cor analyze --session REVIEW_ID
cor review --session REVIEW_ID
cor history --session REVIEW_ID
```

In a terminal, `review` guides you through decisions. Use `cor review --session REVIEW_ID --unit UNIT_ID` to open one decision, or `cor web --session REVIEW_ID --unit UNIT_ID` for its browser view. Use `cor status --session REVIEW_ID --json` to inspect the current version and units programmatically.

An explicit write can be bound to the version you inspected. Reuse the same action ID when retrying an identical request.

```sh
cor review --session REVIEW_ID --unit UNIT_ID --action request_changes \
  --reason "The portal reads jobId but the service returns job_id." \
  --if-version VERSION --action-id UNIQUE_ACTION_ID --yes
```

After editing the files, use `cor capture --session REVIEW_ID --refresh`. To update the objective, criteria, repositories, contracts, or required checks, edit the project JSON and use `cor capture --session REVIEW_ID --config review.json`. Use `cor review --session REVIEW_ID --capture CAPTURE_ID` to inspect an earlier capture.

## Run a trusted check

The demo's Python test verifies the service returns the expected field. Run it against the capture from the service repository.

```sh
cor check --session REVIEW_ID --repo job-manager --name retry --yes -- python3 -m unittest discover -s tests
```

The runner copies the selected repository trees into a temporary directory, runs the command with your OS permissions, and records its exit status and output against the capture. Specify an executable and arguments after `--`. Only run commands from repositories you trust. The runner requires trees without symlinks or submodule entries. Capture also requires a full checkout. Add a separate repository entry for changes inside a submodule.

Add `"required_checks": ["retry"]` to the top level of the project JSON to require a passing result named `retry` for the current capture. Apply the configuration and run the check. A refresh requires fresh test evidence.

## Add independent findings

Local rules run during capture. For an independent pass, choose an installed Ollama model on the same machine, or inspect an evidence packet and import a reviewer's structured response.

```sh
cor analyze --session REVIEW_ID --packet > packet.json
cor analyze --session REVIEW_ID --model INSTALLED_MODEL
cor analyze --session REVIEW_ID --import-report reviewed-findings.json
```

Ollama must already be serving the selected model on loopback port 11434. The packet contains the objective, criteria, bounded excerpts, and a `report_format`. Use that format for imports. Each finding names its decision unit, title, detail, blocking flag, and evidence from that unit. Put assessed change IDs in `assessed` and inconclusive IDs in `unknown`. Use the optional `required_passes` array in project JSON for named passes that must cover all changes before sign-off. An imported finding can inform a human decision. Only a human review action records approval.

## Verify and export

```sh
cor verify --session REVIEW_ID
cor export --session REVIEW_ID --format markdown --output REVIEW_SUMMARY.md
cor export --session REVIEW_ID --format json --output review-ledger.json
```

| `verify` exit code | Meaning |
| --- | --- |
| 0 | Ready for handoff |
| 1 | Blocked. Read the reasons in the output. |
| 2 | Invalid operation or input |

An export includes its readiness state and can be generated while blocked. Read [data handling](../SECURITY.md) before sharing a report.

## Manage the workspace

| Command | Purpose |
| --- | --- |
| `cor demo` | Create or reopen the editable example and print its checkout paths. |
| `cor web --port 0` | Open the web app on an available loopback port. Add `--no-open` to print the address without launching a browser. |
| `cor list` | List reviews saved in the current local workspace. |
| `cor delete --session REVIEW_ID --yes` | Delete the selected review and its stored history. Original repositories and demo checkouts stay on disk. |

Set `COR_HOME` for both clients to use a different data directory, or pass `cor --home /path/to/workspace COMMAND` for a single invocation.
