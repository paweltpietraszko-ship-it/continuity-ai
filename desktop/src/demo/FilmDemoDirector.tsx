import { useCallback, useEffect, useRef, useState } from "react";

import { LiveProjectFlow, type LiveProjectFlowHandle, type LiveProjectFlowPhase } from "../components/LiveProjectFlow";
import type { FilmDemoConfig } from "./filmDemoEnv";
import { FILM_DEMO_SHOTS, shotAt, type DemoShot } from "./filmDemoScript";

interface FilmDemoDirectorProps {
  readonly config: FilmDemoConfig;
  readonly onExit: () => void;
}

const INITIAL_PHASE: LiveProjectFlowPhase = { step: "setup", busy: false, error: null };

function scrollToId(id: string): void {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * Runs exactly one already-existing `LiveProjectFlow` action per shot. Never
 * calls the real Bridge directly and never confirms/approves anything: the
 * "await-manual-approval" and "show-*" shots are display-only, and the
 * mandatory approval click can only ever come from the real button rendered
 * inside `LiveProjectFlow` itself.
 */
async function performShotAction(shot: DemoShot, live: LiveProjectFlowHandle): Promise<void> {
  switch (shot.action) {
    case "create-vault":
      return live.runCreateVault();
    case "load-project":
      return live.runLoadProject();
    case "run-scoping":
      return live.runStartScoping();
    case "generate-report":
      return live.runGenerateReport();
    case "scroll-continuity-break":
      scrollToId("live-continuity-break");
      return;
    case "show-recommended-action":
      scrollToId("live-recommended-action");
      return;
    case "open-evidence-inspector":
      scrollToId("live-evidence-inspector");
      return;
    case "enter":
    case "show-human-review":
    case "await-manual-approval":
    case "show-approved-workspace":
      return;
  }
}

export function FilmDemoDirector({ config, onExit }: FilmDemoDirectorProps) {
  const liveRef = useRef<LiveProjectFlowHandle>(null);
  const [shotIndex, setShotIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [livePhase, setLivePhase] = useState<LiveProjectFlowPhase>(INITIAL_PHASE);
  const [scenarioFailed, setScenarioFailed] = useState<string | null>(null);

  const currentShot = shotAt(shotIndex);
  const isLastShot = shotIndex === FILM_DEMO_SHOTS.length - 1;
  const awaitingManualApproval = currentShot.requiresManualApproval === true && livePhase.step !== "approved";
  const canAdvance = !paused && !scenarioFailed && !livePhase.busy && !isLastShot && !awaitingManualApproval;

  const handleLivePhaseChange = useCallback((phase: LiveProjectFlowPhase) => {
    setLivePhase(phase);
    if (phase.error) {
      // Fail closed: the scenario stops here rather than silently
      // continuing past a Bridge/Codex failure.
      setScenarioFailed(phase.error);
      setPaused(true);
      return;
    }
    // Once the real approval click lands (detected purely from
    // LiveProjectFlow's own retained phase, never assumed), move on to the
    // next, display-only shot.
    setShotIndex((index) => {
      const shot = shotAt(index);
      if (shot.requiresManualApproval && phase.step === "approved") {
        return Math.min(index + 1, FILM_DEMO_SHOTS.length - 1);
      }
      return index;
    });
  }, []);

  const handleContinue = useCallback(async () => {
    if (!canAdvance) return;
    const nextIndex = Math.min(shotIndex + 1, FILM_DEMO_SHOTS.length - 1);
    if (nextIndex === shotIndex) return;
    setShotIndex(nextIndex);
    const live = liveRef.current;
    if (!live) return;
    try {
      await performShotAction(shotAt(nextIndex), live);
    } catch (caught) {
      setScenarioFailed(caught instanceof Error ? caught.message : "The demo step failed.");
      setPaused(true);
    }
  }, [canAdvance, shotIndex]);

  function handleBack(): void {
    setShotIndex((index) => Math.max(index - 1, 0));
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.code !== "Space") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      event.preventDefault();
      void handleContinue();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleContinue]);

  return (
    <div className="film-demo-shell">
      <aside className="film-demo-panel" aria-label="Film demo director">
        <div className="film-demo-shot-number">
          Shot {currentShot.number} / {FILM_DEMO_SHOTS.length}
        </div>
        <h2>{currentShot.name}</h2>
        <p className="film-demo-voiceover">{currentShot.voiceover}</p>
        <p className="film-demo-expected">
          <strong>Expect on screen:</strong> {currentShot.expectedElement}
        </p>

        {awaitingManualApproval ? (
          <p className="film-demo-approval-note" role="status">
            Waiting for the explicit “Confirm scope &amp; materialize approved-only workspace” click below. Continue
            and Space stay disabled until that real click happens.
          </p>
        ) : null}

        {scenarioFailed ? (
          <div className="locked-note" role="alert">
            Scenario stopped: {scenarioFailed}
          </div>
        ) : null}

        <div className="film-demo-controls">
          <button type="button" className="secondary-button" onClick={handleBack} disabled={shotIndex === 0}>
            Back
          </button>
          <button type="button" className="secondary-button" onClick={() => setPaused((value) => !value)}>
            {paused ? "Resume" : "Pause"}
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={() => void handleContinue()}
            disabled={!canAdvance}
          >
            Continue (Space)
          </button>
          <button type="button" className="crumb-button" onClick={onExit}>
            Exit demo
          </button>
        </div>

        <p className="film-demo-status" role="status">
          Request status: {livePhase.busy ? "Working…" : "Idle"}
        </p>

        {isLastShot ? <div className="film-demo-cut-point">CUT POINT — recording can stop here.</div> : null}
      </aside>

      <LiveProjectFlow
        ref={liveRef}
        onBack={onExit}
        demoConfig={config}
        filmDemoMode
        onPhaseChange={handleLivePhaseChange}
      />
    </div>
  );
}
