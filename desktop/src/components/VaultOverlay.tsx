import { useState, type FormEvent } from "react";

interface VaultOverlayProps {
  readonly open: boolean;
  readonly onUnlock: (password: string) => void;
}

export function VaultOverlay({ open, onUnlock }: VaultOverlayProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("Local vault locked. Unlock to add evidence or continue the saved conversation.");

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!password.trim()) {
      setError("Enter the vault password to unlock the local owner session.");
      return;
    }
    onUnlock(password);
    setPassword("");
    setError("Local vault locked. Unlock to add evidence or continue the saved conversation.");
  }

  return (
    <div className={`vault-overlay ${open ? "open" : ""}`} role="dialog" aria-modal="true" aria-labelledby="unlock-heading">
      <div className="vault-card">
        <div className="eyebrow">Local owner</div>
        <h2 id="unlock-heading">Unlock Continuity AI</h2>
        <p>Paweł is recognized as the local owner. Enter the vault password to restore the authenticated session.</p>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="vault-password">Vault password</label>
            <input id="vault-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus={open} />
          </div>
          <button className="primary-button" type="submit">Unlock vault</button>
          <div className="locked-note">{error}</div>
        </form>
      </div>
    </div>
  );
}
