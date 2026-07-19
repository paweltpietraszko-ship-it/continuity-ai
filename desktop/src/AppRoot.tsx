import { useEffect, useState } from "react";

import { App } from "./App";
import type { BridgeBootstrapState } from "./bridge/bootstrap";

const UNAVAILABLE_FALLBACK: BridgeBootstrapState = {
  mode: "unavailable",
  message: "Local Bridge unavailable",
};

export interface AppRootProps {
  // Created once, at module scope, by the caller (main.tsx) — never here —
  // so React.StrictMode re-mounting this component cannot start the Bridge
  // a second time; it only re-subscribes to the same in-flight promise.
  readonly bootstrapPromise: Promise<BridgeBootstrapState>;
}

export function AppRoot({ bootstrapPromise }: AppRootProps) {
  const [bootstrap, setBootstrap] = useState<BridgeBootstrapState>({ mode: "connecting" });

  useEffect(() => {
    let cancelled = false;
    bootstrapPromise
      .then((result) => {
        if (!cancelled) setBootstrap(result);
      })
      .catch(() => {
        if (!cancelled) setBootstrap(UNAVAILABLE_FALLBACK);
      });
    return () => {
      cancelled = true;
    };
  }, [bootstrapPromise]);

  return <App bootstrap={bootstrap} />;
}
