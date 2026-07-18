import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { bootstrapBridge, type BridgeBootstrapState } from "./bridge/bootstrap";
import "./styles/app.css";

const rootElement = document.getElementById("root");

if (rootElement === null) {
  throw new Error("Continuity AI root element is missing.");
}

const reactRoot = ReactDOM.createRoot(rootElement);

// Runs once, outside the React tree, before the first render — React.StrictMode
// double-invokes effects, so Bridge start/stop must not live in a component effect.
bootstrapBridge().then((bootstrap: BridgeBootstrapState) => {
  reactRoot.render(
    <React.StrictMode>
      <App bootstrap={bootstrap} />
    </React.StrictMode>,
  );
});
