# Own the Diff roadmap

Push a feature branch and get a review URL before you open a pull request. If the feature also changes a service, a worker, or a client in another repository, bring those branches onto the same page. Read what the AI built, challenge what seems unnecessary, and invite the team when you can explain the change yourself. When the PRs open, each one points back to that review.

**Available today.** The open-source CLI and local web UI already capture changes across Git repositories, show both sides of a relationship, retain human decisions after a refresh, and export a handoff. You can run local rules, ask an installed Ollama model to examine evidence, or import findings from an independent reviewer. [Try the current release](README.md#try-the-demo) · [How the review engine works](ARCHITECTURE.md)

**Proposed delivery order.** The milestones below describe future work. The first hosted release should earn its place in a developer's workflow on a branch, while there's still time to simplify the implementation.

| Milestone | What a developer or team gains |
| --- | --- |
| 1. Branch previews | Install the GitHub App, push, and open a private URL for one or more branches. |
| 2. Hosted AI review | Get an independent first pass on intent, necessity, conventions, and correctness before requesting team review. |
| 3. Team and PR review | Review related PRs together, discuss decisions, and see which approvals survived the next push. |
| 4. Public plugin and integrations | Install it without help, open a review from Git, and integrate other tools through a documented format. |
| 5. Enterprise rollout | Apply organization policy, choose where source and models run, and audit a decision back to the exact code. |

## 1. A branch push creates a place to review

Start with a publicly installable GitHub App scoped to the repositories a developer or organization selects. Let the installer choose which branches trigger a preview. On the first eligible push, create a draft review, give it a stable URL such as `/r/7nb4` (illustrative), and put an **Open review** link on the commit check. The author can open the page while analysis is running. A team review request is a separate, deliberate action. GitHub supports repository-scoped installations, push webhooks, and a details URL on a commit check. [GitHub Apps](https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/about-creating-github-apps) · [Push events](https://docs.github.com/en/webhooks/webhook-events-and-payloads#push) · [Check runs](https://docs.github.com/en/rest/checks/runs)

**How branches come together.** Suppose the job service and portal use different branch names. From the first page, choose **Add branch**, select the other repository and branch, identify the base for each, and connect the changed response to its caller. For recurring work, allow an explicit shared review ID in project configuration or the CLI. An issue reference or matching branch name can suggest a link for confirmation. If both pushes already created drafts, a user authorized to manage both can join them. Preserve both histories and check access before redirecting their old URLs.

| Repository | Branch | Question to answer on the shared page |
| --- | --- | --- |
| `job-manager` | `retry-response` | Which field does the retry endpoint return? |
| `portal` | `show-retried-job` | Which field does the UI read, and what does the operator see? |

A review has a permanent home and a permalink for each snapshot. A snapshot records the repository, comparison base, and exact head commit for every branch. Later pushes refresh that set. After a rebase, force-push, base change, or branch deletion, show what moved or became unavailable and retain the last reviewable snapshot under the workspace's retention policy. A delayed webhook must never move the page back to an older head.

**Access from day one.** A public installation page lets anyone discover the plugin. Drafts start private to their author. Opening a combined review requires a review grant and current read access to every linked repository. Apply that rule to historical links, exports, and AI findings too. Commit checks visible to a wider audience show a generic link and status. A restricted repository's name, code, and findings belong inside the authorized page.

**Ready for a pilot when** two pushes with different branch names can become one review before either has a PR. Redelivering a push creates no duplicate. A later portal push preserves the URL and the earlier snapshot. A teammate who only has access to the portal cannot retrieve the combined evidence.

## 2. An independent AI review before the team handoff

Run the hosted LLM review as soon as an opted-in branch snapshot is ready. Give it the author's objective, constraints, Git changes, linked interfaces, and relevant existing code at the recorded commits. The developer should be able to add a missing requirement and rerun the affected checks. Use a review context independent of the coding agent's account of its work.

| Review question | What a useful finding looks like |
| --- | --- |
| **Intent. Did we build what was requested?** | “The objective enables retry for failed jobs. This change also permits completed jobs.” Link to the requirement and changed condition. Ask the author when the requirement is missing. |
| **Necessity. Could we remove this and still deliver the feature?** | “This patch opens a second database client. The existing client may serve this caller.” Show both paths, explain the difference in lifecycle, and suggest a test that would establish whether reuse is safe. |
| **Conventions. How does this repository solve the same problem elsewhere?** | Show a comparable endpoint that uses the shared authorization helper. Identify the behavior the new path may lose and let the author explain a deliberate exception. |
| **Correctness. Do the pieces still work together?** | Put the service's `job_id` next to the portal's `jobId`. Show which side the passing unit test exercises and which cross-repository behavior still needs testing. |

Every finding should name its claim, cite navigable evidence, and give the reviewer a way to check it. Record the model, run, and snapshot. Distinguish a verified test result from a predicted consequence. A new class alone is weak evidence of overengineering. If the existing client, caller, or test is outside the permitted context, show what is missing. Let the author accept a finding, dispute it with evidence, or defer it. Only a person can approve the code.

For large features, inventory every changed hunk through Git first. Give the model bounded groups of related changes, cache results against their inputs, and rerun consumers when a provider contract or relevant context changes. Show how much was examined, skipped by policy, or left uncertain. Let each workspace set its model policy, allowed paths, and spend limit. A provider timeout or exhausted budget leaves the page usable and the unfinished pass visible.

Before enabling hosted analysis, show the administrator which provider receives which excerpts and how long inputs and outputs are retained. Keep caches within the workspace's access boundary. Treat code, comments, and PR descriptions as evidence supplied by contributors. They cannot change model policy or grant access to another repository.

**Ready for a pilot when** a test set includes a redundant client, a genuinely necessary second client, a scope change, and an incompatible API field. Reviewers can follow the evidence and distinguish the two client cases. A missing comparison, failed model call, or analysis from an older snapshot cannot count as completed coverage. Publish the evaluation method and record false positives as well as useful catches.

## 3. The same page becomes the team's PR review

When the author chooses **Request team review**, invite people to specific decisions. A service owner and a portal owner can inspect both ends of the interface, leave a discussion on the frozen lines, and see each other's reasoning. When a PR opens, attach it to the existing branch review by repository and ref, reconcile its actual base and head, and surface the same feature URL in the PR check. Show where each PR stands even when one is still a draft or belongs to a later rollout.

- **On the next push**, show a short “since you reviewed” diff. Retain approvals whose evidence and relevant context still match. Reopen a dependent decision when an interface changes, even if the consumer file has no new commit.
- **At handoff**, show the owner of each open decision, outstanding findings, actual CI results, and any missing cross-repository tests. Export a readable PR summary and the exact snapshot that earned approval.
- **At merge**, start with informational checks. Teams can later require named reviewers or passing checks. Recompute affected statuses across all linked PRs whenever any member changes. Each repository still controls its own merge. Show dependency order and compatibility windows when PRs will land separately.

**Ready for team use when** two teammates can review two linked PRs from one URL, a service push reopens the affected portal decision, and both PR checks point to the updated status. A closed or retargeted PR stays intelligible in history. Revoking access removes the reviewer's access to the combined page.

## 4. Make installation and integration routine

Give a solo developer a direct install link, a working public example built from synthetic code, and a path from first push to first decision without configuring CI. Offer teams a self-serve install, onboarding for a second repository, and controls for when notifications start. Seek a GitHub Marketplace listing after the public app is ready for self-service support. [GitHub Marketplace listing requirements](https://docs.github.com/en/apps/github-marketplace/creating-apps-for-github-marketplace/requirements-for-listing-an-app)

Keep the open-source CLI useful offline. Add an optional Git subcommand, with proposed commands such as `git cor open` to open the current branch review and `git cor link` to join related branches. Publish a versioned review manifest and export format so a CI job, editor, or coding agent can attach intent or test evidence with provenance. Give third-party analyzers a narrow API for submitting findings. Human sign-off should stay attributable across every integration.

Expand to GitLab merge requests and other Git hosts once a second adapter can pass the same branch, permission, snapshot, and approval tests. Explore editor links that open the exact lines, issue-tracker links that preserve the approved scope, and replayable examples that a maintainer can share with a first-time contributor. Authors should explicitly opt in to publishing a review assembled entirely from public material.

**Ready for wider distribution when** a developer outside the project can install the app, connect two repositories, review a change, and uninstall it using public documentation alone. Verify that uninstall stops ingestion and that the published deletion and retention controls work.

## 5. Let enterprises choose where the review runs

| Need | Proposed capability | What to demonstrate |
| --- | --- | --- |
| Identity and governance | Organization SSO, directory-based provisioning, reviewer roles, code-owner routing, and policy by repository or path | Revoke membership during a review. Historical pages, exports, and API access honor the revocation. |
| Source and model control | Hosted, private-network, and self-hosted deployment options. Support company-approved model endpoints, redaction, region selection, retention, and deletion. | Review a two-repository feature under a policy that keeps source inside the customer network. Inspect the model request and verify which data crossed the boundary. |
| Release evidence | Audit records for scope, model passes, reviewer identity, exceptions, CI evidence, and the commit set approved for release | Reconstruct who approved an interface, what they saw, and which later change invalidated that approval. |
| Reliability and scale | Queued analysis, per-tenant budgets, incremental updates, backups, restore drills, and observability for delays and failures | Replay a burst of pushes and a worker outage on a 45,000-line, multi-repository fixture. Reconcile all eligible changes and recover the latest review. |

Start with design partners who already ship changes across service boundaries. Choose the first enterprise deployment model around their real procurement, privacy, and operations needs. Publish tested scale limits and deployment instructions as each option becomes supportable.

## Ideas to test once teams use it regularly

| Opportunity | Experiment worth running |
| --- | --- |
| Find callers the author missed | Begin with an API field or event schema change. Search authorized repositories for consumers, let owners confirm the matches, and surface a missing migration in the feature review. |
| Test a smaller implementation | When a reviewer questions a wrapper, let the author compare the original with a revision that reuses existing code. Attach the same trusted CI checks to both and inspect any behavior that changed. |
| Recover why a decision was made | Let a maintainer follow a source line back to the approved snapshot, the alternatives discussed, and the evidence available at the time. Pilot it with an engineer taking over a feature they didn't build. |
| Plan a safe rollout | For an API, SDK, and app released separately, show which old and new versions can coexist, which combinations have test evidence, and who owns each rollout step. |

## How we'll decide what earns the next investment

Pilot on ten real agent-assisted PRs, including features spanning repositories. Use matched changes or different reviewers for the same frozen change. Ask each reviewer to trace a behavior across repositories, explain one implementation choice, and identify what needs rereading after a push. Compare their answers with the frozen code and tests. The proposed target is 30% less median active review time with no increase in missed material issues. Count model waiting time separately. [Original pilot criteria](product-spec.md#14--pilot-and-investment-decision)

| Question | Evidence to collect |
| --- | --- |
| Can developers pick it up on their own? | Time from install to first branch page, first linked repository, and first human decision. Where do people stop? |
| Does it improve understanding? | Time to trace a cross-repository behavior, accuracy of the explanation, and time spent reviewing a second push. |
| Does the model earn attention? | Confirmed defects and unnecessary changes caught, justified dismissals, missed seeded cases, uncovered evidence, latency, and cost per reviewed feature. |
| Can teams depend on it? | Incorrectly carried approvals, stale PR checks, permission failures, and teams choosing the workflow again on a different feature. |

The first hosted milestone to build is small enough for a developer to judge in one sitting. Push two related branches, follow one behavior across both, ask for a correction, and see exactly what the next push changed. That exercise should work before a team is asked to make COR part of its merge policy.
