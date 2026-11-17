# Review a feature across repositories

## Walk through the demo

1. Run `python3 -m cor demo` from the checkout. It creates two editable Git repositories and prints their paths. Run `python3 -m cor web --session "Retry failed jobs"` to open their shared review.
2. Open **Inspect both sides** for **Retry response field**. The Python diff returns `job_id` and the TypeScript diff reads `jobId`. The finding links to both pieces of evidence.
3. Choose **Request changes** and record what the operator would see. Look in **History** or run `python3 -m cor history --session "Retry failed jobs"` to read your decision.
4. In the printed demo portal directory, open `src/jobs/retry.ts`. Change `return result.jobId;` to `return result.job_id;` and save. Choose **Refresh changes**. Reopen the decision and inspect the corrected field. History retains the earlier request against its original capture.
5. Review the other decisions before using **Handoff**. The demo also adds a database client and a service test. The test exercises the Python response. The portal field needs evidence from both repositories. Verification lists the reasons a review is still open.

The same demo is reopened on later runs. For a second independent walkthrough, set `COR_HOME` to a fresh directory before starting either client.

## Choose the comparison for each repository

Start **New review** with the feature objective and the acceptance criteria you would use to decide whether to merge it. Add each local checkout with a short alias. The alias also identifies that repository in relationship definitions and CLI commands.

| Work you want to inspect | Base | Target |
| --- | --- | --- |
| Local edits after the last commit | `HEAD` | `WORKTREE` |
| Local edits including new files | `HEAD` | `WORKTREE`, with untracked files enabled |
| A committed feature | The branch-point commit | The feature commit or ref |

Choose the base independently in every repository. For a committed feature you can find its branch point with `git merge-base main HEAD` in that checkout, substituting its actual target branch for `main`. With a clean working tree, comparing `HEAD` to `WORKTREE` produces an empty review.

## Follow one producer into several consumers

Suppose the service, portal, and worker live in three repositories. Add all three roots to the same review. Declare a **retry response → portal** relationship from the service file to the portal caller, then a **retry response → worker** relationship from the same service file to the worker caller. Write down what each caller expects from the response. Each edge gets a separate decision. Shared evidence counts once toward overall approval coverage.

Declared paths are relative to the corresponding repository and can be globs. The overview can also suggest connections when frozen Python, JavaScript, or TypeScript changes contain an unambiguous HTTP route and caller. Inspect the evidence before confirming a suggestion. A missing counterpart is shown as an evidence gap. Files outside the declared relationships are available as standalone decisions.

## Make and revisit a decision

**Decisions** holds the review queue. Open a decision to inspect the frozen diffs, findings, and evidence. **Files** gives you the complete captured inventory. Approve evidence you understand, request changes with a reason, or defer an open question. A separate dismissal records the reason a blocking finding can be closed. You can also fix the code and refresh.

A refresh captures the selected repositories together. The engine compares the new evidence and scope with the previous capture, carries eligible approvals forward, and records decisions that need another look. Open **History** to revisit an older capture. If another client changes a session while a decision dialog is open, reload the current evidence before submitting a new decision.

## Prepare a handoff

**Handoff** verifies the current Git inputs, review coverage, decisions, blocking findings, and any checks or analysis passes you made mandatory. For a blocked review, act on the listed reasons and run verification again. Export Markdown for a pull request or JSON for a detailed record. Both formats can describe an unfinished review. Inspect the export before sharing it.

See the [CLI reference](cli.md) for trusted checks and analysis packets, and [data handling](../SECURITY.md) for storage and export details.
