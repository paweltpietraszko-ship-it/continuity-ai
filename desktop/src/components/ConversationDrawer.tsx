import { useMemo, useState, type FormEvent } from "react";

import type { ConversationMessage, EvidenceRecord } from "../types/workspace";

interface ConversationDrawerProps {
  readonly open: boolean;
  readonly messages: readonly ConversationMessage[];
  readonly evidence: readonly EvidenceRecord[];
  readonly pendingAttestation: string | null;
  readonly vaultUnlocked: boolean;
  readonly onClose: () => void;
  readonly onSend: (message: string) => void;
  readonly onOpenEvidence: (evidenceId: string) => void;
  readonly onConfirmAttestation: () => void;
  readonly onCancelAttestation: () => void;
}

export function ConversationDrawer({
  open,
  messages,
  evidence,
  pendingAttestation,
  vaultUnlocked,
  onClose,
  onSend,
  onOpenEvidence,
  onConfirmAttestation,
  onCancelAttestation,
}: ConversationDrawerProps) {
  const [value, setValue] = useState("");
  const evidenceMap = useMemo(() => new Map(evidence.map((record) => [record.id, record])), [evidence]);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const message = value.trim();
    if (!message) return;
    onSend(message);
    setValue("");
  }

  return (
    <aside className={`drawer bottom ${open ? "open" : ""}`} aria-hidden={!open} aria-label="Conversation with Continuity AI">
      <div className="drawer-head">
        <h2>Ask Continuity AI</h2>
        <button className="close" type="button" onClick={onClose} aria-label="Close conversation">×</button>
      </div>
      <div className="drawer-body">
        <div className="chat-layout">
          <div className="messages" aria-live="polite">
            {messages.map((message) => (
              <div className={`message ${message.author}`} key={message.id}>
                <div>{message.text}</div>
                {message.citations && message.citations.length > 0 ? (
                  <div className="message-citations">
                    {message.citations.map((citation) => {
                      const record = evidenceMap.get(citation);
                      return record ? (
                        <button className="citation" type="button" key={citation} onClick={() => onOpenEvidence(citation)}>
                          {record.title.replace("Project Aurora ", "")}
                        </button>
                      ) : null;
                    })}
                  </div>
                ) : null}
              </div>
            ))}

            {pendingAttestation ? (
              <section className="attestation-proposal">
                <h3>Pending attestation</h3>
                <p className="muted">Not yet part of project evidence</p>
                <div className="proposal-text">{pendingAttestation}</div>
                <p className="muted proposal-note">It will be saved with Paweł’s authenticated local identity, timestamp, and desktop text channel.</p>
                <div className="proposal-actions">
                  <button className="confirm-button" type="button" onClick={onConfirmAttestation} disabled={!vaultUnlocked}>Confirm attestation</button>
                  <button className="quiet-button" type="button" onClick={onCancelAttestation}>Cancel</button>
                </div>
                {!vaultUnlocked ? <p className="locked-inline">Unlock the vault before confirming this attestation.</p> : null}
              </section>
            ) : null}
          </div>

          <form className="chat-form" onSubmit={submit}>
            <label htmlFor="continuity-chat">Ask Continuity AI…</label>
            <textarea
              id="continuity-chat"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="Ask what changed, why the report says this, or add a statement to the project record."
            />
            <button className="primary-button" type="submit">Send</button>
          </form>
        </div>
      </div>
    </aside>
  );
}
