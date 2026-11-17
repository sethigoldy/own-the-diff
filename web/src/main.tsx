import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import type {
  View,
  Unit,
  FileRecord,
  Config,
  Repo,
  Contract,
  Summary,
  Verification,
  Finding,
} from "./types";
import { route, link, matches, sideFiles, findingDismissed } from "./model.js";
import "./style.css";
import { Advanced } from "./Advanced";
import { Connections } from "./Connections";

async function api<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch("/api" + path, {
    headers: {
      "X-COR-Request": "1",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    ...(body !== undefined
      ? { method: "POST", body: JSON.stringify(body) }
      : {}),
  });
  if (!r.ok) {
    let message = `Request failed (${r.status})`;
    try {
      message = (await r.json()).error || message;
    } catch {}
    throw new Error(message);
  }
  return r.json();
}
const short = (s: string) => s?.slice(0, 10) || "—";
const readable = (s: string) => s.replaceAll("_", " ");
function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={"badge " + tone}>{children}</span>;
}
function Empty({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">◇</span>
      <h3>{title}</h3>
      <div>{children}</div>
    </div>
  );
}
function Patch({ file }: { file: FileRecord }) {
  return (
    <div className="patch">
      {file.atoms.map((a) => (
        <div key={a.id} className="atom">
          <div className="atom-label">
            {a.kind} · {short(a.id)}
          </div>
          <pre tabIndex={0} aria-label={`Frozen diff for ${file.path}`}>
            {a.patch.split("\n").map((line, i) => (
              <span
                key={i}
                className={
                  line.startsWith("+") && !line.startsWith("+++")
                    ? "addition"
                    : line.startsWith("-") && !line.startsWith("---")
                      ? "deletion"
                      : line.startsWith("@@")
                        ? "hunk"
                        : ""
                }
              >
                {line || " "}
                <br />
              </span>
            ))}
          </pre>
        </div>
      ))}
      {file.atoms.length === 0 && (
        <p className="muted pad">No diff atoms were recorded for this file.</p>
      )}
    </div>
  );
}

function Setup({
  close,
  created,
  initial,
}: {
  close: () => void;
  created: (v: View) => void;
  initial?: View;
}) {
  const [title, setTitle] = useState(initial?.title || ""),
    [objective, setObjective] = useState(initial?.objective || ""),
    [criteria, setCriteria] = useState(
      initial?.config.criteria.join("\n") || "",
    ),
    [repos, setRepos] = useState<Repo[]>(
      initial?.config.repos || [
        {
          alias: "",
          path: "",
          base: "HEAD",
          target: "WORKTREE",
          include_untracked: false,
        },
      ],
    ),
    [contracts, setContracts] = useState<Contract[]>(
      initial?.config.contracts || [],
    ),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [requiredChecks, setRequiredChecks] = useState(
      initial?.config.required_checks?.join("\n") || "",
    ),
    [requiredPasses, setRequiredPasses] = useState(
      initial?.config.required_passes?.join("\n") || "",
    );
  const update = (i: number, key: keyof Repo, value: string | boolean) =>
    setRepos((rs) => rs.map((r, n) => (n === i ? { ...r, [key]: value } : r)));
  const edge = (i: number, key: keyof Contract, value: unknown) =>
    setContracts((es) =>
      es.map((e, n) => (n === i ? { ...e, [key]: value } : e)),
    );
  async function choose(i: number) {
    try {
      const r = await api<{ path: string | null }>("/folder", {});
      if (r.path) update(i, "path", r.path);
    } catch (e) {
      setError(String(e));
    }
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const config: Config = {
        title,
        objective,
        repos,
        contracts,
        criteria: criteria
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
        required_checks: requiredChecks
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
        required_passes: requiredPasses
          .split("\n")
          .map((x) => x.trim())
          .filter(Boolean),
      };
      created(
        initial
          ? await api<View>(
              "/sessions/" + encodeURIComponent(initial.id) + "/config",
              { version: initial.version, config },
            )
          : await api<View>("/sessions", config),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="setup-wrap">
      <form className="setup" onSubmit={submit}>
        <div className="section-head">
          <div>
            <div className="eyebrow">
              {initial ? "Update review scope" : "A new local review"}
            </div>
            <h1>
              {initial ? "Revise the contract." : "Start with the behavior."}
            </h1>
          </div>
          <button type="button" onClick={close}>
            Cancel
          </button>
        </div>
        <p className="muted">
          Choose the repositories and declare what should change. Capture reads
          Git without editing your repositories.
        </p>
        {error && (
          <div role="alert" className="notice danger">
            {error}
          </div>
        )}
        <div className="form-grid">
          <label>
            Review title
            <input
              required
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Retry failed jobs"
            />
          </label>
          <label className="wide">
            Objective
            <textarea
              required
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              placeholder="Describe the behavior and the boundaries of this change."
            />
          </label>
          <label className="wide">
            Acceptance criteria <span className="muted">one per line</span>
            <textarea
              value={criteria}
              onChange={(e) => setCriteria(e.target.value)}
              placeholder="Only failed jobs can be retried.\nPreserve resource-level authorization."
            />
          </label>
        </div>
        <div className="section-head">
          <h2>
            Repositories <span className="number">{repos.length}</span>
          </h2>
          <button
            type="button"
            onClick={() =>
              setRepos([
                ...repos,
                {
                  alias: "",
                  path: "",
                  base: "HEAD",
                  target: "WORKTREE",
                  include_untracked: false,
                },
              ])
            }
          >
            + Add repository
          </button>
        </div>
        {repos.map((r, i) => (
          <fieldset className="repo-form" key={i}>
            <legend>Repository {i + 1}</legend>
            <div className="form-grid">
              <label>
                Alias
                <input
                  required
                  value={r.alias}
                  placeholder="job-manager"
                  pattern="[A-Za-z0-9_.-]+"
                  onChange={(e) => update(i, "alias", e.target.value)}
                />
              </label>
              <label>
                Local folder
                <div className="input-action">
                  <input
                    required
                    value={r.path}
                    placeholder="/path/to/repository"
                    onChange={(e) => update(i, "path", e.target.value)}
                  />
                  <button type="button" onClick={() => choose(i)}>
                    Choose…
                  </button>
                </div>
              </label>
              <label>
                Base ref
                <input
                  required
                  value={r.base}
                  onChange={(e) => update(i, "base", e.target.value)}
                />
              </label>
              <label>
                Target
                <input
                  required
                  value={r.target}
                  placeholder="WORKTREE or a Git ref"
                  onChange={(e) => update(i, "target", e.target.value)}
                />
              </label>
            </div>
            <div className="section-head small">
              <label className="check">
                <input
                  type="checkbox"
                  checked={r.include_untracked}
                  onChange={(e) =>
                    update(i, "include_untracked", e.target.checked)
                  }
                />{" "}
                Include untracked files
              </label>
              {repos.length > 1 && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setRepos(repos.filter((_, n) => n !== i))}
                >
                  Remove
                </button>
              )}
            </div>
          </fieldset>
        ))}
        <p className="fine">
          WORKTREE captures the final tracked files on disk, including staged
          and unstaged edits. Untracked files are included only when selected.
        </p>
        <div className="section-head">
          <div>
            <h2>Declared relationships</h2>
            <p className="muted">
              Connect a producer to its consumer. Use an external alias and
              relative path for an unavailable repository; missing evidence
              stays visible.
            </p>
          </div>
          <button
            type="button"
            onClick={() =>
              setContracts([
                ...contracts,
                {
                  id:
                    "C-" +
                    (Math.max(
                      0,
                      ...contracts.map(
                        (c) => Number(c.id.replace(/^C-/, "")) || 0,
                      ),
                    ) +
                      1),
                  title: "",
                  expectation: "",
                  producer: { repo: repos[0]?.alias || "", path: "" },
                  consumer: { repo: repos[1]?.alias || "", path: "" },
                },
              ])
            }
          >
            + Add relationship
          </button>
        </div>
        {contracts.map((c, i) => (
          <fieldset className="repo-form" key={i}>
            <legend>{c.id}</legend>
            <div className="form-grid">
              <label>
                Relationship title
                <input
                  required
                  value={c.title}
                  onChange={(e) => edge(i, "title", e.target.value)}
                />
              </label>
              <label>
                Expected behavior
                <input
                  required
                  value={c.expectation}
                  onChange={(e) => edge(i, "expectation", e.target.value)}
                />
              </label>
              {(["producer", "consumer"] as const).map((side) => (
                <div key={side}>
                  <span className="field-label">{side}</span>
                  <div className="input-action">
                    <input
                      required
                      aria-label={`${side} repository`}
                      list={`repos-${i}-${side}`}
                      placeholder="Repository or external alias"
                      value={c[side].repo}
                      onChange={(e) =>
                        edge(i, side, { ...c[side], repo: e.target.value })
                      }
                    />
                    <datalist id={`repos-${i}-${side}`}>
                      {repos
                        .filter((r) => r.alias)
                        .map((r) => (
                          <option key={r.alias} value={r.alias} />
                        ))}
                    </datalist>
                    <input
                      required
                      aria-label={`${side} path`}
                      placeholder="path/to/file or glob"
                      value={c[side].path}
                      onChange={(e) =>
                        edge(i, side, { ...c[side], path: e.target.value })
                      }
                    />
                  </div>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="text-button remove"
              onClick={() => setContracts(contracts.filter((_, n) => n !== i))}
            >
              Remove relationship
            </button>
          </fieldset>
        ))}
        <details className="policy-setup">
          <summary>Required checks and review passes</summary>
          <p className="fine">
            Required names block readiness until current evidence exists. One
            stable name per line.
          </p>
          <div className="form-grid">
            <label>
              Required check names
              <textarea
                value={requiredChecks}
                onChange={(e) => setRequiredChecks(e.target.value)}
                placeholder="retry-contract"
              />
            </label>
            <label>
              Required pass names
              <textarea
                value={requiredPasses}
                onChange={(e) => setRequiredPasses(e.target.value)}
                placeholder="scope"
              />
            </label>
          </div>
        </details>
        <div className="setup-footer">
          <p className="muted">
            The complete multi-repository capture is published only if every
            repository succeeds.
          </p>
          <button className="primary" disabled={busy} type="submit">
            {busy
              ? "Capturing repositories…"
              : initial
                ? "Save scope & recapture →"
                : "Capture changes →"}
          </button>
        </div>
      </form>
    </div>
  );
}

function App() {
  const [location, setLocation] = useState(() => route(window.location.hash)),
    [sessions, setSessions] = useState<Summary[]>([]),
    [view, setView] = useState<View | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [connected, setConnected] = useState(true),
    [latest, setLatest] = useState<View | null>(null),
    [setup, setSetup] = useState(false),
    [editing, setEditing] = useState(false),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState(""),
    [repo, setRepo] = useState(""),
    [status, setStatus] = useState(""),
    [verify, setVerify] = useState<Verification | null>(null),
    [pageSize, setPageSize] = useState(40),
    [toast, setToast] = useState("");
  const [confirmation, setConfirmation] = useState<{
      unit: Unit;
      action: string;
      finding?: Finding;
      version: number;
      capture: string;
    } | null>(null),
    [reason, setReason] = useState("");
  const modalRef = useRef<HTMLFormElement>(null);
  const viewed = useRef(view);
  viewed.current = view;
  const historical = Boolean(location.capture),
    stale = Boolean(
      latest &&
      view &&
      (latest.version !== view.version || latest.capture !== view.capture),
    ),
    locked = busy || !connected || historical || stale;

  useEffect(() => {
    if (!confirmation) return;
    const prior = document.activeElement as HTMLElement | null;
    const handle = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) {
        setConfirmation(null);
        return;
      }
      if (e.key === "Tab") {
        const items = Array.from(
          modalRef.current?.querySelectorAll<HTMLElement>(
            "button:not(:disabled),textarea,input,a[href],summary",
          ) || [],
        ).filter((el) => el.getClientRects().length);
        const first = items[0],
          last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handle);
    modalRef.current?.querySelector<HTMLElement>("textarea")?.focus();
    return () => {
      document.removeEventListener("keydown", handle);
      prior?.focus();
    };
  }, [confirmation, busy]);
  async function deleteReview() {
    if (
      !view ||
      !window.confirm(
        `Permanently delete the local review “${view.title}” and its saved captures, evidence, and decisions? Your source repositories are kept intact.`,
      )
    )
      return;
    setBusy(true);
    try {
      await api("/sessions/" + encodeURIComponent(view.id) + "/delete", {
        version: view.version,
      });
      window.location.hash = "";
      setView(null);
      await loadSessions();
      setToast("Local review deleted. Source repositories were kept.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function loadSessions() {
    try {
      const r = await api<{ sessions: Summary[] }>("/sessions");
      setSessions(r.sessions);
      setConnected(true);
      return r.sessions;
    } catch (e) {
      setConnected(false);
      setError((e as Error).message);
      return [];
    }
  }
  const accept = (v: View) => {
    setView(v);
    setLatest(null);
    setVerify(null);
    setConnected(true);
    setError("");
  };
  useEffect(() => {
    const handler = () => setLocation(route(window.location.hash));
    window.addEventListener("hashchange", handler);
    loadSessions().then(() => setLoading(false));
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  useEffect(() => {
    if (!location.session) {
      setView(null);
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    setError("");
    setConfirmation(null);
    setSearch("");
    setRepo("");
    setStatus("");
    api<View>(
      "/sessions/" +
        encodeURIComponent(location.session) +
        (location.capture
          ? "?capture=" + encodeURIComponent(location.capture)
          : ""),
    )
      .then((v) => {
        if (live) accept(v);
      })
      .catch((e) => {
        if (live) {
          setError(e.message);
          setConnected(false);
        }
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [location.session, location.capture]);
  useEffect(() => {
    if (!location.session || location.capture) return;
    let alive = true;
    const tick = async () => {
      try {
        const revision = await api<{ version: number; capture: string }>(
          "/sessions/" + encodeURIComponent(location.session!) + "/revision",
        );
        if (!alive) return;
        setConnected(true);
        const old = viewed.current;
        if (
          old &&
          (revision.version !== old.version || revision.capture !== old.capture)
        ) {
          const v = await api<View>(
            "/sessions/" + encodeURIComponent(location.session!),
          );
          if (alive) setLatest(v);
        }
      } catch {
        if (alive) setConnected(false);
      }
    };
    const timer = setInterval(tick, 6000);
    const focus = () => {
      void tick();
    };
    window.addEventListener("focus", focus);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener("focus", focus);
    };
  }, [location.session, location.capture]);
  useEffect(() => {
    setPageSize(40);
  }, [search, repo, status, location.page]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 4000);
      return () => clearTimeout(t);
    }
  }, [toast]);
  async function demo() {
    setBusy(true);
    setError("");
    try {
      const v = await api<View>("/demo", {});
      accept(v);
      await loadSessions();
      window.location.hash = link(v.id);
      setSetup(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    if (!view) return;
    setBusy(true);
    setError("");
    try {
      accept(
        await api<View>(
          "/sessions/" + encodeURIComponent(view.id) + "/refresh",
          { version: view.version },
        ),
      );
      setToast("New capture saved. Check History for decisions that reopened.");
    } catch (e) {
      setError((e as Error).message);
      try {
        setLatest(await api<View>("/sessions/" + encodeURIComponent(view.id)));
      } catch {
        setConnected(false);
      }
    } finally {
      setBusy(false);
    }
  }
  function ask(unit: Unit, action: string, finding?: Finding) {
    if (!view) return;
    setReason("");
    setConfirmation({
      unit,
      action,
      finding,
      version: view.version,
      capture: view.capture,
    });
  }
  async function decide(e: React.FormEvent) {
    e.preventDefault();
    if (!view || !confirmation) return;
    setBusy(true);
    setError("");
    try {
      const v = await api<View>(
        "/sessions/" + encodeURIComponent(view.id) + "/decisions",
        {
          unit_id: confirmation.unit.id,
          action: confirmation.action,
          reason,
          version: confirmation.version,
          capture: confirmation.capture,
          action_id: crypto.randomUUID(),
          ...(confirmation.finding
            ? { finding_id: confirmation.finding.id }
            : {}),
        },
      );
      accept(v);
      setConfirmation(null);
      setToast("Decision recorded against the frozen evidence.");
    } catch (e) {
      setError((e as Error).message);
      try {
        setLatest(await api<View>("/sessions/" + encodeURIComponent(view.id)));
      } catch {
        setConnected(false);
      }
    } finally {
      setBusy(false);
    }
  }
  async function verification() {
    if (!view) return;
    setBusy(true);
    try {
      setVerify(
        await api<Verification>(
          "/sessions/" + encodeURIComponent(view.id) + "/verify",
        ),
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function advanced(suffix: string, body: unknown) {
    if (!view) return;
    setBusy(true);
    setError("");
    try {
      accept(
        await api<View>(
          "/sessions/" + encodeURIComponent(view.id) + "/" + suffix,
          body,
        ),
      );
      setToast("Review ledger updated.");
    } catch (e) {
      setError((e as Error).message);
      try {
        setLatest(await api<View>("/sessions/" + encodeURIComponent(view.id)));
      } catch {
        setConnected(false);
      }
      throw e;
    } finally {
      setBusy(false);
    }
  }
  const files =
    view?.repositories.flatMap((r) =>
      r.files.map((f) => ({ ...f, repo: f.repo || r.alias })),
    ) || [];
  const filtered =
    view?.units.filter((u) => matches(u, search, repo, status)) || [];
  const chosen = view?.units.find((u) => u.id === location.item);
  const contract = chosen
    ? view?.config.contracts.find((c) => c.id === chosen.contract_id)
    : undefined;
  const unitFiles = chosen
    ? files.filter(
        (f) =>
          chosen.file_ids.includes(f.id) ||
          f.atoms.some((a) => chosen.atom_ids.includes(a.id)),
      )
    : [];
  const unitLink = (u: Unit) =>
    link(view!.id, "decisions", u.id, location.capture);
  function renderSide(side: Contract["producer"], role: string) {
    const frozenSide = chosen?.sides?.[role.toLowerCase()];
    const fs = frozenSide
      ? files.filter(file => frozenSide.file_ids.includes(file.id))
      : sideFiles(files, side) as FileRecord[];
    const contexts = frozenSide?.contexts.filter(ctx => !fs.some(file => file.path === ctx.path)) || [];
    return (
      <section className="evidence">
        <header>
          <div className="eyebrow">{role}</div>
          <h3>{side.repo || "Repository unavailable"}</h3>
          <code>{side.path || "No path declared"}</code>
          <span className="fine">Frozen capture {short(view!.capture)}</span>
        </header>
        {fs.map((f) => (
            <React.Fragment key={f.id}>
              <Patch file={f} />
              <a
                className="evidence-link"
                href={link(view!.id, "files", f.id, view!.capture)}
              >
                Open full {role.toLowerCase()} diff ↗
              </a>
            </React.Fragment>
          ))}
        {contexts.map(ctx => (
          <details key={ctx.path} className="frozen-source">
            <summary>Unchanged counterpart · {ctx.path}</summary>
            <small>Captured blob {short(ctx.oid)}</small>
            <pre tabIndex={0}>{ctx.text ?? "Opaque content; inspect the recorded blob identity."}</pre>
          </details>
        ))}
        {!fs.length && !contexts.length && (
          <div className="missing">
            <strong>Counterpart evidence unavailable</strong>
            <p>
              {side.repo && side.path
                ? "No file at this path is available in the selected capture. Inspect the declared path and repository."
                : "This side is unavailable. Declare the repository and path in a new review."}
            </p>
          </div>
        )}
      </section>
    );
  }
  function rows(units: Unit[]) {
    return (
      <div className="unit-list">
        {units.map((u) => (
          <a className="unit-row" href={unitLink(u)} key={u.id}>
            <span className={"risk-dot " + u.risk} />
            <div>
              <div className="row-title">{u.title}</div>
              <p>{u.summary}</p>
              <span className="fine">
                {u.repos.join(" + ")} · {u.atom_ids.length} changes
              </span>
            </div>
            <div className="row-end">
              <Badge
                tone={
                  u.status === "approved"
                    ? "green"
                    : u.status === "pending"
                      ? "neutral"
                      : "amber"
                }
              >
                {readable(u.status)}
              </Badge>
              <span className="arrow">↗</span>
            </div>
          </a>
        ))}
      </div>
    );
  }
  return (
    <>
      <a className="skip" href="#content">
        Skip to content
      </a>
      <header className="topbar">
        <a href="#" className="brand" aria-label="All reviews">
          <span className="logo">
            <i />
          </span>
          <span>
            Code Ownership<span className="brand-light"> Review</span>
          </span>
        </a>
        <div className="top-meta">
          <span className={"connection-dot " + (!connected ? "offline" : "")} />
          <span>{connected ? "Local workspace" : "Disconnected"}</span>
          <span className="top-divider" />
          <span className="mono">
            {view ? "Capture " + short(view.capture) : "Review ledger"}
          </span>
        </div>
        <button
          className="top-new"
          onClick={() => {
            setEditing(false);
            setSetup(true);
          }}
        >
          + New review
        </button>
      </header>
      {setup ? (
        <Setup
          initial={editing ? view || undefined : undefined}
          close={() => setSetup(false)}
          created={(v) => {
            accept(v);
            setSetup(false);
            loadSessions();
            window.location.hash = link(v.id);
          }}
        />
      ) : (
        <main id="content" className="workspace">
          {error && (
            <div className="notice danger" role="alert">
              <strong>Could not complete the request.</strong> {error}
              <button
                onClick={() => {
                  setError("");
                  loadSessions();
                }}
              >
                Retry connection
              </button>
            </div>
          )}
          {loading ? (
            <Empty title="Opening your review…">
              Loading the saved capture and decisions.
            </Empty>
          ) : !view ? (
            <>
              <div className="landing-head">
                <div className="eyebrow">Code ownership, made explicit</div>
                <h1>
                  Follow the change.
                  <br />
                  <span>Own the decision.</span>
                </h1>
                <p>
                  Bring connected repositories into one review. Inspect both
                  sides of a behavior, then sign off on the exact evidence.
                </p>
                <div className="button-row">
                  <button
                    className="primary"
                    onClick={() => {
                      setEditing(false);
                      setSetup(true);
                    }}
                  >
                    Start a review →
                  </button>
                  <button disabled={busy} onClick={demo}>
                    {busy ? "Preparing demo…" : "Explore the working demo"}
                  </button>
                </div>
                <p className="fine">
                  Runs locally · No account · No source uploads
                </p>
              </div>
              <div className="section-head">
                <h2>
                  Your reviews <span className="number">{sessions.length}</span>
                </h2>
                <button className="text-button" onClick={loadSessions}>
                  Refresh list ↻
                </button>
              </div>
              {sessions.length ? (
                <div className="session-grid">
                  {sessions.map((s) => (
                    <a className="session-card" key={s.id} href={link(s.id)}>
                      <span className="eyebrow">Saved local review</span>
                      <h3>{s.title}</h3>
                      <p>Updated {new Date(s.updated_at).toLocaleString()}</p>
                      <span className="text-link">Resume review ↗</span>
                    </a>
                  ))}
                </div>
              ) : (
                <Empty title="A clear place to start">
                  Add your local repositories, or open the demo to review a real
                  producer and consumer.
                </Empty>
              )}
            </>
          ) : (
            <>
              <div className="breadcrumb">
                <a href="#">Reviews</a>
                <span>/</span>
                <select
                  aria-label="Switch review"
                  value={view.id}
                  onChange={(e) =>
                    (window.location.hash = link(e.target.value))
                  }
                >
                  {sessions.some((s) => s.id === view.id) ? null : (
                    <option value={view.id}>{view.title}</option>
                  )}
                  {sessions.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                </select>
              </div>
              <div className="review-heading">
                <div>
                  <div className="eyebrow">Feature review</div>
                  <h1>{view.title}</h1>
                  <p>{view.objective}</p>
                </div>
                <button onClick={refresh} disabled={locked}>
                  ↻ {busy ? "Working…" : "Refresh changes"}
                </button>
              </div>
              <div className="metrics">
                <div>
                  <strong>
                    {view.repositories.length.toString().padStart(2, "0")}
                  </strong>
                  <span>repositories</span>
                </div>
                <div>
                  <strong>
                    {view.counts.units.toString().padStart(2, "0")}
                  </strong>
                  <span>review decisions</span>
                </div>
                <div>
                  <strong>
                    {view.counts.atoms.toString().padStart(2, "0")}
                  </strong>
                  <span>frozen changes</span>
                </div>
                <div className="approval-metric">
                  <div>
                    <strong>
                      {view.counts.approved}
                      <span> / {view.counts.atoms}</span>
                    </strong>
                    <span>human approved</span>
                  </div>
                  <div
                    className="progress"
                    role="progressbar"
                    aria-label="Human approval"
                    aria-valuenow={view.counts.approved}
                    aria-valuemin={0}
                    aria-valuemax={view.counts.atoms || 1}
                  >
                    <i
                      style={{
                        width:
                          (view.counts.atoms
                            ? (100 * view.counts.approved) / view.counts.atoms
                            : 0) + "%",
                      }}
                    />
                  </div>
                </div>
              </div>
              {!connected && (
                <div role="status" className="notice danger">
                  Connection lost. Showing the last loaded evidence. Decisions
                  are disabled until the local service reconnects.
                </div>
              )}
              {stale && (
                <div role="status" className="notice amber">
                  <div>
                    <strong>This review changed in another client.</strong>
                    <br />
                    Your current evidence and draft are preserved. Load the
                    latest version before recording a decision.
                  </div>
                  <button
                    onClick={() => {
                      accept(latest!);
                      setConfirmation(null);
                      setReason("");
                    }}
                  >
                    Load latest capture
                  </button>
                </div>
              )}
              {historical && (
                <div className="notice amber">
                  <div>
                    <strong>Historical evidence · {short(view.capture)}</strong>{" "}
                    · This saved capture is read only.
                  </div>
                  <a href={link(view.id, location.page, location.item)}>
                    Open current review →
                  </a>
                </div>
              )}
              <nav className="tabs" aria-label="Review sections">
                {["overview", "decisions", "files", "history", "handoff"].map(
                  (p) => (
                    <a
                      key={p}
                      href={link(view.id, p, null, location.capture)}
                      className={location.page === p ? "active" : ""}
                      aria-current={location.page === p ? "page" : undefined}
                    >
                      {p[0].toUpperCase() + p.slice(1)}
                      {p === "decisions" && (
                        <span>
                          {
                            view.units.filter((u) => u.status !== "approved")
                              .length
                          }
                        </span>
                      )}
                    </a>
                  ),
                )}
                <button
                  className="cli-button"
                  onClick={async () => {
                    const command = [
                      "cor review --session " + view.id,
                      chosen && "--unit " + chosen.id,
                      historical && "--capture " + view.capture,
                    ].filter(Boolean).join(" ");
                    try {
                      await navigator.clipboard.writeText(command);
                      setToast("CLI command copied.");
                    } catch {
                      setToast(command);
                    }
                  }}
                >
                  ⌘ Copy CLI command
                </button>
              </nav>
              {(location.page === "overview" ||
                (location.page === "decisions" && !chosen) ||
                location.page === "files") && (
                <div className="filters">
                  <label className="search">
                    <span>⌕</span>
                    <input
                      aria-label="Search review"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder={
                        location.page === "files"
                          ? "Search captured paths and patches…"
                          : "Search decisions and evidence…"
                      }
                    />
                  </label>
                  <select
                    aria-label="Filter repository"
                    value={repo}
                    onChange={(e) => setRepo(e.target.value)}
                  >
                    <option value="">All repositories</option>
                    {view.repositories.map((r) => (
                      <option key={r.alias}>{r.alias}</option>
                    ))}
                  </select>
                  {location.page !== "files" && (
                    <select
                      aria-label="Filter decision status"
                      value={status}
                      onChange={(e) => setStatus(e.target.value)}
                    >
                      <option value="">All decisions</option>
                      {[
                        "pending",
                        "approved",
                        "changes_requested",
                        "deferred",
                        "stale",
                      ].map((s) => (
                        <option key={s} value={s}>
                          {readable(s)}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              )}
              {location.page === "overview" && (
                <>
                  <div className="section-head">
                    <div>
                      <div className="eyebrow">Connected behavior</div>
                      <h2>How the change travels</h2>
                    </div>
                    <span className="fine">
                      Producer → consumer · counterpart always visible
                    </span>
                  </div>
                  <Connections
                    view={view}
                    locked={locked}
                    save={advanced}
                    capture={location.capture}
                  />
                  <div className="relationships">
                    {view.config.contracts
                      .filter(
                        (c) =>
                          !repo ||
                          c.producer.repo === repo ||
                          c.consumer.repo === repo,
                      )
                      .map((c) => {
                        const unit = view.units.find(
                          (u) => u.contract_id === c.id,
                        );
                        return (
                          <article className="relationship" key={c.id}>
                            <div className="section-head small">
                              <h3>
                                <span className="contract-id">{c.id}</span>
                                {c.title}
                              </h3>
                              {unit && (
                                <Badge
                                  tone={
                                    unit.risk === "high" ? "amber" : "neutral"
                                  }
                                >
                                  {unit.risk} risk · {readable(unit.status)}
                                </Badge>
                              )}
                            </div>
                            <div className="flow">
                              {(["producer", "consumer"] as const).map(
                                (side, i) => (
                                  <React.Fragment key={side}>
                                    {i === 1 && (
                                      <div className="flow-arrow">
                                        <span>declared interface</span>
                                        <b>→</b>
                                      </div>
                                    )}
                                    <div
                                      className={
                                        "flow-node " +
                                        (repo && repo !== c[side].repo
                                          ? "counterpart"
                                          : "")
                                      }
                                    >
                                      <div className="eyebrow">
                                        {side}
                                        {repo && repo !== c[side].repo
                                          ? " · counterpart"
                                          : ""}
                                      </div>
                                      <strong>
                                        {c[side].repo || "Unavailable"}
                                      </strong>
                                      <code>
                                        {c[side].path || "No path declared"}
                                      </code>
                                      {sideFiles(files, c[side]).length ===
                                        0 && (
                                        <span className="fine">
                                          No captured change on this side
                                        </span>
                                      )}
                                    </div>
                                  </React.Fragment>
                                ),
                              )}
                            </div>
                            <div className="relationship-bottom">
                              <p>{c.expectation}</p>
                              {unit ? (
                                <a href={unitLink(unit)}>
                                  Inspect both sides <span>↗</span>
                                </a>
                              ) : (
                                <span className="muted">
                                  No decision attached
                                </span>
                              )}
                            </div>
                          </article>
                        );
                      })}
                    {view.config.contracts.length === 0 && (
                      <Empty title="No relationships declared">
                        All captured changes are available below and in Files.
                        Add producer and consumer paths in Handoff → Edit review scope.
                      </Empty>
                    )}
                  </div>
                  <div className="section-head">
                    <div>
                      <div className="eyebrow">Next in the queue</div>
                      <h2>Decisions that need your attention</h2>
                    </div>
                    <a
                      href={link(view.id, "decisions", null, location.capture)}
                    >
                      View all decisions →
                    </a>
                  </div>
                  {filtered.length ? (
                    rows(filtered.slice(0, 6))
                  ) : (
                    <Empty title="No matching decisions">
                      Try another repository or search. Coverage above always
                      includes the complete review.
                    </Empty>
                  )}
                  <div className="repo-strip">
                    {view.repositories.map((r) => (
                      <div key={r.alias}>
                        <strong>{r.alias}</strong>
                        <span>
                          {r.files.length} files ·{" "}
                          {r.files.reduce((n, f) => n + f.atoms.length, 0)}{" "}
                          changes
                        </span>
                        <code>
                          {short(r.base_sha)} → {short(r.target_id)}
                        </code>
                      </div>
                    ))}
                  </div>
                </>
              )}
              {location.page === "decisions" &&
                (chosen ? (
                  <>
                    <div className="section-head decision-heading">
                      <div>
                        <a
                          className="back-link"
                          href={link(
                            view.id,
                            "decisions",
                            null,
                            location.capture,
                          )}
                        >
                          ← Decision queue
                        </a>
                        <h2>{chosen.title}</h2>
                        <p>{chosen.summary}</p>
                      </div>
                      <Badge
                        tone={chosen.risk === "high" ? "amber" : "neutral"}
                      >
                        {chosen.risk} risk · {readable(chosen.status)}
                      </Badge>
                    </div>
                    {chosen.reason && (
                      <div className="notice">
                        Last decision / refresh: {chosen.reason}
                      </div>
                    )}
                    {contract ? (
                      <>
                        <div className="paired">
                          {renderSide(contract.producer, "Producer")}
                          {renderSide(contract.consumer, "Consumer")}
                        </div>
                        <section className="expectation">
                          <div className="section-head small">
                            <strong>Expected behavior</strong>
                            <span className="fine">
                              {contract.id} · Declared relationship
                            </span>
                          </div>
                          <p>{contract.expectation}</p>
                          <span className="fine">
                            Checks:{" "}
                            {
                              (view.checks || []).filter(
                                (c) => c.capture === view.capture,
                              ).length
                            }{" "}
                            trusted runs at this capture,{" "}
                            {
                              (view.checks || []).filter(
                                (c) =>
                                  c.capture === view.capture &&
                                  c.exit_code === 0,
                              ).length
                            }{" "}
                            passed. See Handoff for results.
                          </span>
                        </section>
                      </>
                    ) : (
                      <div className="paired">
                        {unitFiles.map((f) => (
                          <section className="evidence" key={f.id}>
                            <header>
                              <div className="eyebrow">{f.repo}</div>
                              <h3>{f.path}</h3>
                              <span className="fine">
                                Frozen capture {short(view.capture)}
                              </span>
                            </header>
                            <Patch file={f} />
                            <a
                              className="evidence-link"
                              href={link(view.id, "files", f.id, view.capture)}
                            >
                              Open full frozen diff ↗
                            </a>
                          </section>
                        ))}
                      </div>
                    )}
                    {chosen.findings.length > 0 && (
                      <section className="findings">
                        <div className="section-head">
                          <h3>Findings & evidence</h3>
                          <span className="fine">
                            Approval does not dismiss a blocker
                          </span>
                        </div>
                        {chosen.findings.map((f) => {
                          const dismissed = findingDismissed(view, chosen, f);
                          return (
                            <article className="finding" key={f.id}>
                              <div>
                                <Badge
                                  tone={
                                    dismissed
                                      ? "green"
                                      : f.blocking
                                        ? "amber"
                                        : "neutral"
                                  }
                                >
                                  {dismissed
                                    ? "Dismissed with evidence"
                                    : f.blocking
                                      ? "Blocking finding"
                                      : "Observation"}
                                </Badge>
                                <h3>{f.title}</h3>
                                <p>{f.detail}</p>
                                <div className="evidence-refs">
                                  {f.evidence.map((a) => {
                                    const file = files.find((x) =>
                                      x.atoms.some((atom) => atom.id === a),
                                    );
                                    return file ? (
                                      <a
                                        key={a}
                                        href={link(
                                          view.id,
                                          "files",
                                          file.id,
                                          view.capture,
                                        )}
                                      >
                                        {file.repo}/{file.path} · {short(a)} ↗
                                      </a>
                                    ) : (
                                      <span key={a}>
                                        Unavailable evidence {short(a)}
                                      </span>
                                    );
                                  })}
                                </div>
                              </div>
                              {f.blocking && !dismissed && (
                                <button
                                  disabled={locked}
                                  onClick={() => ask(chosen, "dismiss", f)}
                                >
                                  Dismiss with evidence
                                </button>
                              )}
                            </article>
                          );
                        })}
                      </section>
                    )}
                    <div className="decision-footer">
                      <span className="fine">
                        {chosen.id} · {chosen.atom_ids.length} frozen changes ·{" "}
                        {chosen.repos.join(" + ")}
                      </span>
                      <div className="button-row">
                        <button
                          disabled={locked}
                          onClick={() => ask(chosen, "defer")}
                        >
                          Defer
                        </button>
                        <button
                          disabled={locked}
                          onClick={() => ask(chosen, "approve")}
                        >
                          Approve…
                        </button>
                        <button
                          className="primary"
                          disabled={locked}
                          onClick={() => ask(chosen, "request_changes")}
                        >
                          Request changes
                        </button>
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="section-head">
                      <h2>Review decisions</h2>
                      <span className="fine">
                        {filtered.length} of {view.units.length} decisions ·
                        filters do not change coverage
                      </span>
                    </div>
                    {filtered.length ? (
                      rows(filtered.slice(0, pageSize))
                    ) : (
                      <Empty title="No matching decisions">
                        Clear your filters to see the complete queue.
                      </Empty>
                    )}
                    {filtered.length > pageSize && (
                      <button
                        className="load-more"
                        onClick={() => setPageSize(pageSize + 40)}
                      >
                        Show next 40 decisions
                      </button>
                    )}
                  </>
                ))}
              {location.page === "files" &&
                (() => {
                  const displayed = files.filter(
                    (f) =>
                      (!repo || f.repo === repo) &&
                      (!search ||
                        [
                          f.path,
                          f.old_path,
                          f.repo,
                          ...f.atoms.map((a) => a.patch),
                        ]
                          .join(" ")
                          .toLowerCase()
                          .includes(search.toLowerCase())),
                  );
                  const selected = files.find((f) => f.id === location.item);
                  return (
                    <>
                      <div className="section-head">
                        <h2>Complete file inventory</h2>
                        <span className="fine">
                          {displayed.length} of {files.length} files ·{" "}
                          {view.counts.atoms} total changes
                        </span>
                      </div>
                      <div className="file-browser">
                        <aside aria-label="Captured files">
                          {displayed.slice(0, pageSize).map((f) => (
                            <a
                              key={f.id}
                              href={link(
                                view.id,
                                "files",
                                f.id,
                                location.capture,
                              )}
                              className={
                                selected?.id === f.id ? "selected" : ""
                              }
                            >
                              <span className="file-status">{f.status}</span>
                              <div>
                                <span className="fine">{f.repo}</span>
                                <strong>{f.path}</strong>
                                <span className="fine">
                                  {f.atoms.length} changes
                                </span>
                              </div>
                            </a>
                          ))}
                          {displayed.length > pageSize && (
                            <button onClick={() => setPageSize(pageSize + 40)}>
                              Show next 40 files
                            </button>
                          )}
                          {!displayed.length && (
                            <p className="pad muted">
                              No files match your filters.
                            </p>
                          )}
                        </aside>
                        <section className="file-content">
                          {selected ? (
                            <>
                              <header>
                                <div className="eyebrow">
                                  {selected.repo} · {selected.status}
                                </div>
                                <h3>{selected.path}</h3>
                                {selected.old_path &&
                                  selected.old_path !== selected.path && (
                                    <p>Renamed from {selected.old_path}</p>
                                  )}
                                <p className="fine">
                                  Frozen capture {short(view.capture)} ·{" "}
                                  {selected.old_mode || "absent"} →{" "}
                                  {selected.new_mode || "absent"}
                                </p>
                                <div className="blob-ids">
                                  <span>
                                    Before{" "}
                                    <code>{selected.old_oid || "absent"}</code>
                                  </span>
                                  <span>
                                    After{" "}
                                    <code>{selected.new_oid || "absent"}</code>
                                  </span>
                                </div>
                              </header>
                              <Patch file={selected} />
                              {(["old_text", "new_text"] as const).map(key =>
                                typeof selected[key] === "string" ? (
                                  <details className="frozen-source" key={key}>
                                    <summary>{key === "old_text" ? "Before" : "After"} · full frozen source</summary>
                                    <pre tabIndex={0}>{selected[key]}</pre>
                                  </details>
                                ) : null
                              )}
                            </>
                          ) : (
                            <Empty
                              title={
                                files.length
                                  ? "Choose a file to inspect"
                                  : "Nothing to review"
                              }
                            >
                              {files.length
                                ? "Every hunk, binary and metadata transition stays in this inventory."
                                : "No differences were captured between the configured bases and targets."}
                            </Empty>
                          )}
                        </section>
                      </div>
                    </>
                  );
                })()}
              {location.page === "history" && (
                <>
                  <div className="section-head">
                    <div>
                      <div className="eyebrow">The review ledger</div>
                      <h2>Every capture. Every decision.</h2>
                    </div>
                    <span className="fine">Append-only local history</span>
                  </div>
                  {view.events.length ? (
                    <ol className="timeline">
                      {[...view.events].reverse().map((event, i) => (
                        <li key={i}>
                          <div className="timeline-dot" />
                          <div>
                            <div className="section-head small">
                              <h3>{readable(event.action)}</h3>
                              <time>
                                {new Date(event.time).toLocaleString()}
                              </time>
                            </div>
                            <p>
                              {event.reason ||
                                "Recorded against the frozen capture."}
                            </p>
                            <div className="fine">
                              {event.unit_id && (
                                <span>
                                  {view.units.find(
                                    (u) => u.id === event.unit_id,
                                  )?.title || event.unit_id}{" "}
                                  ·{" "}
                                </span>
                              )}
                              <a
                                href={link(
                                  view.id,
                                  event.unit_id ? "decisions" : "overview",
                                  event.unit_id,
                                  event.capture,
                                )}
                              >
                                Capture {short(event.capture)} ↗
                              </a>
                            </div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <Empty title="No human decisions yet">
                      Review activity will appear here as you capture and record
                      decisions.
                    </Empty>
                  )}
                </>
              )}
              {location.page === "handoff" && (
                <>
                  <div className="handoff-hero">
                    <div>
                      <div className="eyebrow">Before the pull request</div>
                      <h2>Make the remaining work explicit.</h2>
                      <p>
                        Verify current Git inputs against this capture, then
                        export the review and its evidence.
                      </p>
                    </div>
                    <button
                      className="primary"
                      disabled={locked}
                      onClick={verification}
                    >
                      {busy ? "Verifying…" : "Verify review →"}
                    </button>
                  </div>
                  {verify ? (
                    <div
                      className={
                        "verification " + (verify.ready ? "ready" : "")
                      }
                    >
                      <Badge tone={verify.ready ? "green" : "amber"}>
                        {verify.ready
                          ? "Ready under the recorded policy"
                          : "Not ready for handoff"}
                      </Badge>
                      <h3>
                        {verify.ready
                          ? "Current evidence meets the review gate."
                          : `${verify.blockers.length} blockers require attention`}
                      </h3>
                      <p className="fine">
                        Verified capture {short(verify.capture)} · tests are not
                        implied by human sign-off.
                      </p>
                      {verify.blockers.length > 0 && (
                        <ul>
                          {verify.blockers.map((b, i) => (
                            <li key={i}>{b}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ) : (
                    <div className="notice">
                      <strong>
                        Readiness has not been verified in this browser.
                      </strong>{" "}
                      Select Verify review to check current repository inputs
                      and the shared ledger.
                    </div>
                  )}
                  <div className="export-grid">
                    <article>
                      <span className="eyebrow">For the pull request</span>
                      <h3>Review summary</h3>
                      <p>
                        A readable Markdown handoff with coverage, snapshot IDs,
                        decisions and outstanding blockers.
                      </p>
                      <a
                        className={"button " + (locked ? "disabled" : "")}
                        aria-disabled={locked}
                        href={
                          locked
                            ? undefined
                            : "/api/sessions/" +
                              encodeURIComponent(view.id) +
                              "/export?format=markdown"
                        }
                        download
                      >
                        Export Markdown ↓
                      </a>
                    </article>
                    <article>
                      <span className="eyebrow">For the full audit</span>
                      <h3>Evidence ledger</h3>
                      <p>
                        A versioned machine-readable record of frozen changes,
                        findings and human decisions.
                      </p>
                      <a
                        className={"button " + (locked ? "disabled" : "")}
                        aria-disabled={locked}
                        href={
                          locked
                            ? undefined
                            : "/api/sessions/" +
                              encodeURIComponent(view.id) +
                              "/export?format=json"
                        }
                        download
                      >
                        Export JSON ↓
                      </a>
                    </article>
                  </div>
                  <Advanced view={view} locked={locked} run={advanced} />
                  <div className="section-head">
                    <h3>Review scope</h3>
                    <div className="button-row">
                      <button
                        disabled={locked}
                        onClick={() => {
                          setEditing(true);
                          setSetup(true);
                        }}
                      >
                        Edit scope & recapture…
                      </button>
                      <button
                        disabled={locked}
                        className="text-button"
                        onClick={deleteReview}
                      >
                        Delete review…
                      </button>
                    </div>
                  </div>
                  <div className="expectation">
                    <p>{view.objective}</p>
                    {view.config.criteria.length ? (
                      <ol>
                        {view.config.criteria.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ol>
                    ) : (
                      <p className="muted">
                        No acceptance criteria were declared.
                      </p>
                    )}
                  </div>
                </>
              )}
              <footer className="workspace-footer">
                <span>
                  <span className="connection-dot" /> Frozen evidence · local
                  ledger
                </span>
                <span>
                  Capture {short(view.capture)} · Version {view.version} ·{" "}
                  {
                    (view.checks || []).filter(
                      (c) => c.capture === view.capture,
                    ).length
                  }{" "}
                  trusted checks recorded
                </span>
              </footer>
            </>
          )}
        </main>
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
      {confirmation && view && (
        <div className="modal-scrim">
          <form
            ref={modalRef}
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            onSubmit={decide}
          >
            <div className="section-head">
              <div className="eyebrow">Explicit human decision</div>
              <button
                type="button"
                aria-label="Close confirmation"
                onClick={() => setConfirmation(null)}
              >
                ✕
              </button>
            </div>
            <h2 id="confirm-title">
              {confirmation.action === "approve"
                ? "Approve these exact changes?"
                : confirmation.action === "dismiss"
                  ? "Dismiss this blocking finding?"
                  : confirmation.action === "defer"
                    ? "Save an open question"
                    : "Request a change"}
            </h2>
            <h3>{confirmation.finding?.title || confirmation.unit.title}</h3>
            <p className="muted">
              Capture {short(confirmation.capture)} · version{" "}
              {confirmation.version} · {confirmation.unit.atom_ids.length}{" "}
              changes across {confirmation.unit.repos.join(" + ")}
            </p>
            {confirmation.action === "approve" && (
              <>
                <p>
                  This approval applies to these frozen atoms. Separate blocking
                  findings still require an evidence-backed disposition.
                </p>
                <details>
                  <summary>Inspect the exact approval scope</summary>
                  <ul className="atom-scope">
                    {confirmation.unit.atom_ids.map((id) => {
                      const f = files.find((f) =>
                        f.atoms.some((a) => a.id === id),
                      );
                      return (
                        <li key={id}>
                          <code>{id}</code>
                          <span>
                            {f ? f.repo + "/" + f.path : "Unavailable evidence"}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                  {files
                    .filter(
                      (f) =>
                        confirmation.unit.file_ids.includes(f.id) ||
                        f.atoms.some((a) =>
                          confirmation.unit.atom_ids.includes(a.id),
                        ),
                    )
                    .map((f) => (
                      <div key={f.id}>
                        <strong>
                          {f.repo}/{f.path}
                        </strong>
                        <Patch
                          file={{
                            ...f,
                            atoms: f.atoms.filter((a) =>
                              confirmation.unit.atom_ids.includes(a.id),
                            ),
                          }}
                        />
                      </div>
                    ))}
                </details>
              </>
            )}
            <label>
              {confirmation.action === "dismiss"
                ? "Reason and frozen evidence supporting dismissal"
                : confirmation.action === "request_changes"
                  ? "What needs to change?"
                  : confirmation.action === "defer"
                    ? "What question remains open?"
                    : "Review note (optional)"}
              <textarea
                autoFocus
                required={confirmation.action !== "approve"}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={
                  confirmation.action === "dismiss"
                    ? "Cite the captured path / atom and explain why the finding does not apply."
                    : ""
                }
              />
            </label>
            {stale && (
              <div className="notice amber">
                A newer version exists. This draft cannot be submitted. Close
                and load the latest capture.
              </div>
            )}
            <div className="button-row modal-actions">
              <button type="button" onClick={() => setConfirmation(null)}>
                Cancel
              </button>
              <button
                className="primary"
                disabled={
                  locked ||
                  (confirmation.action !== "approve" && !reason.trim())
                }
                type="submit"
              >
                {busy
                  ? "Recording…"
                  : confirmation.action === "approve"
                    ? "Confirm approval"
                    : confirmation.action === "dismiss"
                      ? "Record dismissal"
                      : confirmation.action === "defer"
                        ? "Save deferral"
                        : "Record change request"}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
