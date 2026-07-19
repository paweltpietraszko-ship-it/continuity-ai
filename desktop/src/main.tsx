import React from "react";
import ReactDOM from "react-dom/client";

import { AppRoot } from "./AppRoot";
import { bootstrapBridge } from "./bridge/bootstrap";
import "./styles/app.css";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("Continuity AI root element is missing.");
}

// Created once, at true module scope — never inside a component or effect —
// so React.StrictMode's double-invoked effects cannot start the Bridge
// twice. The React shell mounts immediately in AppRoot's "connecting" state
// and updates once this promise settles; it never waits for the Python
// process before rendering.
const bootstrapPromise = bootstrapBridge();

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <AppRoot bootstrapPromise={bootstrapPromise} />
  </React.StrictMode>,
);
