# Contributing to Own the Diff

Start with the [demo](README.md#try-the-demo). If a change affects review behavior, try the same review in the browser and CLI. Both clients read the same capture and decision history.

## Development setup

Install Git and Python 3.9 or newer. To work on the browser, also install Node.js 22 and npm. From the repository root, run the Python suite and build a disposable demo.

```sh
python3 -m unittest discover -v
export COR_HOME="$(mktemp -d)"
python3 -m cor demo
python3 -m cor web --session "Retry failed jobs"
```

For browser changes, run the frontend tests and production build.

```sh
cd web
npm ci
npm test
npm run build
```

The build type-checks TypeScript and writes the production assets into `cor/static/`. Include those assets with changes to the browser source so users can run a checkout without installing Node. See the [frontend guide](web/README.md) for the development server.

## Where changes belong

| Area | Files |
| --- | --- |
| Git inventory, frozen patches, repository identity | `cor/inventory.py` |
| Scope, grouping, analysis, verification, decision history | `cor/analysis.py`, `cor/engine.py` |
| Trusted check runner, model integration, export filters | `cor/checks.py`, `cor/assistance.py`, `cor/privacy.py` |
| Terminal and local HTTP endpoints | `cor/cli.py`, `cor/server.py` |
| Browser views and interactions | `web/src/` |
| Git fixtures and regression tests | `tests/`, `web/tests/` |

The [architecture](ARCHITECTURE.md) explains the boundaries. The [product specification](product-spec.md) records design goals and pilot criteria. Use the implementation and tests for current behavior.

## Submit a change

Describe which review task improves, how to reproduce the old behavior, and how you checked the new result. A synthetic two-repository fixture is particularly helpful for a cross-repository bug. For browser changes include a screenshot of the affected view. For changes to capture, verification, or decision carry-forward, exercise an edit and refresh, then inspect the historical capture.

Use the [issue templates](https://github.com/sethigoldy/own-the-diff/issues/new/choose) for a bug or a feature proposal. For a security-sensitive report, follow the [private reporting instructions](SECURITY.md).
