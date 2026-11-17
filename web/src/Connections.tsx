import { useState } from "react";
import type { Contract, View } from "./types";
import { connectedContracts, link } from "./model.js";

export function Connections({
  view,
  locked,
  save,
  capture,
}: {
  view: View;
  locked: boolean;
  save: (suffix: string, body: unknown) => Promise<void>;
  capture: string | null;
}) {
  const [error, setError] = useState("");
  const groups = connectedContracts(view.config.contracts);
  const suggestions = (view.suggested_contracts || []).filter(
    (s) =>
      !view.config.contracts.some(
        (c) =>
          c.producer.repo === s.producer.repo &&
          c.producer.path === s.producer.path &&
          c.consumer.repo === s.consumer.repo &&
          c.consumer.path === s.consumer.path,
      ),
  );
  async function confirm(s: Contract) {
    if (
      !window.confirm(
        `Add the inferred connection “${s.title}” to the declared review scope? This creates a new capture and reopens decisions affected by the scope change.`,
      )
    )
      return;
    const id = view.config.contracts.some((c) => c.id === s.id)
      ? `C-${crypto.randomUUID().slice(0, 8)}`
      : s.id;
    const contract = {
      id,
      title: s.title,
      expectation: s.expectation,
      producer: s.producer,
      consumer: s.consumer,
    };
    try {
      await save("config", {
        version: view.version,
        config: {
          ...view.config,
          contracts: [...view.config.contracts, contract],
        },
      });
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <>
      {groups.some((g) => g.repos.length >= 3) && (
        <section
          className="connected-paths"
          aria-label="Connected declared paths"
        >
          <div className="eyebrow">Follow the declared paths</div>
          <p className="fine">
            Each arrow is a declared producer-to-consumer relationship. Shared
            repositories connect the edges; separate groups are independent.
          </p>
          {groups.map((group, i) => (
            <div key={i} className="path-group">
              <h3>{group.repos.join(" · ")}</h3>
              <ol>
                {group.edges.map((edge) => {
                  const unit = view.units.find(
                    (u) => u.contract_id === edge.id,
                  );
                  return (
                    <li key={edge.id}>
                      <span className="path-end">
                        <strong>{edge.producer.repo}</strong>
                        <code>{edge.producer.path}</code>
                      </span>
                      <span className="path-arrow" aria-label="produces for">
                        →
                      </span>
                      <span className="path-end">
                        <strong>{edge.consumer.repo}</strong>
                        <code>{edge.consumer.path}</code>
                      </span>
                      {unit ? (
                        <a href={link(view.id, "decisions", unit.id, capture)}>
                          {edge.title} ↗
                        </a>
                      ) : (
                        <span className="fine">{edge.title}</span>
                      )}
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </section>
      )}
      {suggestions.length > 0 && (
        <details className="suggested-connections">
          <summary>
            Suggested connections{" "}
            <span className="number">{suggestions.length}</span>
            <span className="fine">
              Inferred · not part of your approved scope
            </span>
          </summary>
          <div>
            {error && (
              <p role="alert" className="notice danger">
                {error}
              </p>
            )}
            {suggestions.map((s) => (
              <article key={s.id}>
                <div>
                  <span className="eyebrow">Inferred connection</span>
                  <h3>{s.title}</h3>
                  <p>
                    <code>
                      {s.producer.repo}/{s.producer.path}
                    </code>
                    <span aria-label="produces for"> → </span>
                    <code>
                      {s.consumer.repo}/{s.consumer.path}
                    </code>
                  </p>
                  <p className="fine">{s.basis || s.expectation}</p>
                </div>
                <button disabled={locked} onClick={() => confirm(s)}>
                  Confirm & add to scope…
                </button>
              </article>
            ))}
          </div>
        </details>
      )}
    </>
  );
}
