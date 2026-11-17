export function route(hash) {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  const parts = path.split("/").map(decodeURIComponent);
  return {
    session: parts[0] === "review" ? parts[1] : null,
    page: parts[2] || "overview",
    item: parts[3] || null,
    capture: new URLSearchParams(query).get("capture"),
  };
}
/** @param {string} session @param {string} [page] @param {string|null} [item] @param {string|null} [capture] */
export function link(session, page = "overview", item = null, capture = null) {
  return (
    "#review/" +
    encodeURIComponent(session) +
    "/" +
    page +
    (item ? "/" + encodeURIComponent(item) : "") +
    (capture ? "?capture=" + encodeURIComponent(capture) : "")
  );
}
export function matches(unit, search, repo, status) {
  return (
    (!repo || unit.repos.includes(repo)) &&
    (!status || unit.status === status) &&
    (!search ||
      [
        unit.title,
        unit.summary,
        unit.id,
        unit.repos.join(" "),
        ...unit.findings.map((f) => f.title + " " + f.detail),
      ]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase()))
  );
}
export function sideFiles(files, side) {
  if (!side?.repo || !side?.path) return [];
  const pattern =
    "^" +
    side.path
      .split("*")
      .map((p) => p.replace(/[.+?^${}()|[\]\\]/g, "\\$&"))
      .join(".*") +
    "$";
  return files.filter(
    (f) => f.repo === side.repo && new RegExp(pattern).test(f.path),
  );
}
export function findingDismissed(view, unit, finding) {
  return Boolean(
    finding.dismissed ||
    finding.disposition === "dismissed" ||
    finding.disposition?.action === "dismissed" ||
    view.events.some(
      (e) =>
        e.action === "dismiss" &&
        e.unit_id === unit.id &&
        e.capture === view.capture &&
        (e.finding_id === finding.id ||
          (!e.finding_id &&
            unit.findings.filter((f) => f.blocking).length === 1)),
    ),
  );
}

// Group only declared edges sharing a repository; each arrow stays a direct claim.
export function connectedContracts(contracts) {
  const remaining = [...contracts];
  const groups = [];
  while (remaining.length) {
    const edges = [remaining.shift()];
    const repos = new Set([edges[0].producer.repo, edges[0].consumer.repo]);
    let changed = true;
    while (changed) {
      changed = false;
      for (let i = remaining.length - 1; i >= 0; i--) {
        const edge = remaining[i];
        if (repos.has(edge.producer.repo) || repos.has(edge.consumer.repo)) {
          edges.push(edge);
          repos.add(edge.producer.repo);
          repos.add(edge.consumer.repo);
          remaining.splice(i, 1);
          changed = true;
        }
      }
    }
    groups.push({ repos: [...repos], edges });
  }
  return groups;
}
