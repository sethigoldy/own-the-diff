import { test } from "node:test";
import assert from "node:assert/strict";
import {
  route,
  link,
  matches,
  sideFiles,
  findingDismissed,
} from "../src/model.js";
test("capture links round trip with encoded ids", () => {
  assert.deepEqual(route(link("a b", "decisions", "u/1", "cap 2")), {
    session: "a b",
    page: "decisions",
    item: "u/1",
    capture: "cap 2",
  });
});
test("filter only controls list and preserves multi-repo unit", () => {
  assert.equal(
    matches(
      {
        title: "Retry",
        summary: "",
        id: "u",
        repos: ["api", "portal"],
        status: "pending",
        findings: [],
      },
      "retry",
      "portal",
      "pending",
    ),
    true,
  );
});
test("declared side matches patterns and escapes regex", () => {
  const files = [
    { repo: "api", path: "src/a.py" },
    { repo: "api", path: "src/aXpy" },
    { repo: "other", path: "src/a.py" },
  ];
  assert.equal(sideFiles(files, { repo: "api", path: "src/*.py" }).length, 1);
  assert.equal(sideFiles(files, { repo: "api", path: "" }).length, 0);
});
test("old dismissal cannot resolve current capture", () => {
  const u = { id: "u", findings: [{ id: "f", blocking: true }] };
  assert.equal(
    findingDismissed(
      {
        capture: "b",
        events: [
          { action: "dismiss", unit_id: "u", capture: "a", finding_id: "f" },
        ],
      },
      u,
      u.findings[0],
    ),
    false,
  );
});

test("engine-carried dismissal remains authoritative after refresh", () => {
  const finding = {
    id: "f",
    blocking: true,
    disposition: { action: "dismissed", capture: "older" },
  };
  assert.equal(
    findingDismissed(
      { capture: "new", events: [] },
      { id: "u", findings: [finding] },
      finding,
    ),
    true,
  );
});

test("multi-hop groups retain directions without inventing independent links", async () => {
  const { connectedContracts } = await import("../src/model.js");
  const edge = (id, producer, consumer) => ({
    id,
    producer: { repo: producer },
    consumer: { repo: consumer },
  });
  const groups = connectedContracts([
    edge("1", "api", "shared"),
    edge("2", "shared", "portal"),
    edge("3", "worker", "database"),
  ]);
  assert.equal(groups.length, 2);
  assert.deepEqual(groups[0].repos, ["api", "shared", "portal"]);
  assert.deepEqual(
    groups[0].edges.map((e) => [e.producer.repo, e.consumer.repo]),
    [
      ["api", "shared"],
      ["shared", "portal"],
    ],
  );
});
