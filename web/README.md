# Browser interface

The production assets in `../cor/static/` are served by `python3 -m cor web`.
To change or rebuild the UI, run these commands from the repository root.

```sh
cd web
npm ci
npm run typecheck
npm test
npm run build
```

React, JavaScript, styles, and icons are bundled locally. No remote fonts, CDN,
provider calls, or source transfer occur when loading the interface. Optional
analysis sends explicitly opted-in excerpts to local Ollama through the backend.

The browser reads shared engine state. Revision polling flags changes without
replacing an open capture or pending confirmation. Decisions carry the viewed
version and capture; concurrency conflicts preserve the draft. Historical
capture links are read only. Global approval counts remain independent of filters.

`npm run dev` is for UI development only; its `/api` proxy targets the default
loopback backend on port 8765. Use the bundled production service for the full
same-origin security flow and end-to-end verification.
