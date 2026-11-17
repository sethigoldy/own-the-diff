import { useState } from "react";
import type { View } from "./types";
export function Advanced({
  view,
  locked,
  run,
}: {
  view: View;
  locked: boolean;
  run: (suffix: string, body: unknown) => Promise<void>;
}) {
  const [model, setModel] = useState("qwen2.5-coder:7b"),
    [optIn, setOptIn] = useState(false),
    [name, setName] = useState(""),
    [repo, setRepo] = useState(view.repositories[0]?.alias || ""),
    [argv, setArgv] = useState('["python3", "-m", "unittest"]'),
    [trusted, setTrusted] = useState(false),
    [checkOpen, setCheckOpen] = useState(false),
    [report, setReport] = useState(""),
    [error, setError] = useState("");
  const bound = { version: view.version, capture: view.capture };
  async function submit(suffix: string, body: unknown) {
    setError("");
    try {
      await run(suffix, body);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function check(e: React.FormEvent) {
    e.preventDefault();
    try {
      const args = JSON.parse(argv);
      if (
        !Array.isArray(args) ||
        !args.length ||
        args.some((a) => typeof a !== "string")
      )
        throw new Error(
          "Command arguments must be a non-empty JSON array of strings.",
        );
      await submit("check", { ...bound, name, repo, argv: args });
      setCheckOpen(false);
      setTrusted(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function importReport() {
    try {
      const parsed = JSON.parse(report);
      await submit("import", { ...bound, report: parsed });
      setReport("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const checks = view.checks || [];
  return (
    <details className="advanced">
      <summary>
        Analysis, reviewer packets & trusted checks{" "}
        <span className="fine">
          Optional tools · human review still required
        </span>
      </summary>
      <div className="advanced-body">
        {error && (
          <div className="notice danger" role="alert">
            {error}
          </div>
        )}
        <section>
          <div className="eyebrow">Independent second look</div>
          <h3>Analyze with a local model</h3>
          <p className="muted">
            Send bounded eligible changed excerpts to your local Ollama service.
            Model findings are proposals; they cannot approve changes or
            establish test results.
          </p>
          <div className="input-action">
            <input
              aria-label="Ollama model name"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="Ollama model name"
            />
            <button
              disabled={locked || !optIn || !model.trim()}
              onClick={() => submit("analyze", { ...bound, model })}
            >
              Analyze with local model
            </button>
          </div>
          <label className="check advanced-check">
            <input
              type="checkbox"
              checked={optIn}
              onChange={(e) => setOptIn(e.target.checked)}
            />{" "}
            I allow this capture’s excerpts to be sent to local Ollama.
          </label>
        </section>
        <section>
          <div className="eyebrow">Bring your own reviewer</div>
          <h3>Export and import a review packet</h3>
          <p className="muted">
            Download frozen evidence for an external reviewer. Inspect their
            JSON report before importing it. Evidence references are validated
            by the shared engine.
          </p>
          <a
            className={"button " + (locked ? "disabled" : "")}
            aria-disabled={locked}
            href={"/api/sessions/" + encodeURIComponent(view.id) + "/packet"}
            download
          >
            Download reviewer packet ↓
          </a>
          <label className="report-file">
            Load reviewer JSON
            <input
              type="file"
              accept=".json,application/json"
              disabled={locked}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (file) {
                  if (file.size > 5_000_000) {
                    setError("Choose a report smaller than 5 MB.");
                    return;
                  }
                  setReport(await file.text());
                }
              }}
            />
          </label>
          <label>
            Report preview
            <textarea
              value={report}
              onChange={(e) => setReport(e.target.value)}
              placeholder="Paste reviewer JSON or choose a file"
            />
          </label>
          <button disabled={locked || !report.trim()} onClick={importReport}>
            Validate and import report
          </button>
        </section>
        <section>
          <div className="eyebrow">Execution with provenance</div>
          <h3>Run a trusted check</h3>
          <p className="muted">
            A command you explicitly trust runs on an isolated copy of the
            captured repository. Choose the command yourself; repository content
            cannot grant trust.
          </p>
          <button disabled={locked} onClick={() => setCheckOpen(!checkOpen)}>
            {checkOpen ? "Hide check setup" : "Configure a check…"}
          </button>
          {checkOpen && (
            <form className="check-form" onSubmit={check}>
              <div className="form-grid">
                <label>
                  Check name
                  <input
                    required
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Retry contract tests"
                  />
                </label>
                <label>
                  Repository
                  <select
                    value={repo}
                    onChange={(e) => setRepo(e.target.value)}
                  >
                    {view.repositories.map((r) => (
                      <option key={r.alias}>{r.alias}</option>
                    ))}
                  </select>
                </label>
                <label className="wide">
                  Command arguments (JSON array)
                  <textarea
                    required
                    value={argv}
                    onChange={(e) => setArgv(e.target.value)}
                  />
                </label>
              </div>
              <label className="check advanced-check">
                <input
                  type="checkbox"
                  checked={trusted}
                  onChange={(e) => setTrusted(e.target.checked)}
                />{" "}
                I reviewed this command and explicitly trust its execution on an
                isolated copy.
              </label>
              <button
                className="primary"
                disabled={locked || !trusted || !name.trim()}
                type="submit"
              >
                Confirm and run check
              </button>
            </form>
          )}
          {checks.length > 0 && (
            <div className="check-results">
              {checks.map((c, i) => (
                <details key={c.id || i}>
                  <summary>
                    <span
                      className={
                        "badge " + (c.exit_code === 0 ? "green" : "amber")
                      }
                    >
                      {c.exit_code === 0
                        ? "Passed"
                        : c.exit_code === undefined
                          ? "Recorded"
                          : "Failed"}
                    </span>{" "}
                    {c.name || "Trusted check"}{" "}
                    <span className="fine">
                      {c.repo} · capture {(c.capture || "").slice(0, 10)}
                      {c.capture !== view.capture ? " · historical" : ""}
                    </span>
                  </summary>
                  <pre>{JSON.stringify(c, null, 2)}</pre>
                </details>
              ))}
            </div>
          )}
        </section>
      </div>
    </details>
  );
}
