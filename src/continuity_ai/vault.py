"""Local encrypted vault core."""
from __future__ import annotations
import base64, json, os, tempfile, uuid
from pathlib import Path
from typing import Any
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from continuity_ai.domain import AuditEvent, AttestationProposal, AnalysisRevisionProposal, AuthenticatedUserAttestation, OwnerProfile, SavedAnalysis, VaultSession, utc_now
from continuity_ai.errors import VaultAuthError, VaultLockedError, ValidationError, VaultAlreadyExistsError
from continuity_ai.retained_analysis import saved_analysis_from_payload, saved_analysis_to_payload
from continuity_ai.source_scoping.domain import ApprovedSourceScope
from continuity_ai.source_scoping.serialization import approved_scope_from_payload, approved_scope_to_payload

FORMAT="continuity-ai-vault"; VERSION=1
KDF={"algorithm":"argon2id","time_cost":3,"memory_cost":65536,"parallelism":4,"hash_len":32,"version":19}

def _b64(b: bytes) -> str: return base64.b64encode(b).decode("ascii")
def _ub64(s: str) -> bytes: return base64.b64decode(s.encode("ascii"))
def derive(password: str, salt: bytes) -> bytes:
    return hash_secret_raw(password.encode("utf-8"), salt, time_cost=KDF["time_cost"], memory_cost=KDF["memory_cost"], parallelism=KDF["parallelism"], hash_len=32, type=Type.ID, version=KDF["version"])
def _aad() -> bytes: return f"{FORMAT}:{VERSION}".encode()
def empty_payload(name: str) -> dict[str, Any]:
    owner=OwnerProfile("ACT-"+uuid.uuid4().hex, name, utc_now())
    return {"schema_version":1,"vault_id":"VAULT-"+uuid.uuid4().hex,"owner":owner.__dict__,"attestations":[],"saved_analyses":[],"approved_source_scopes":[],"conversation":[],"audit_events":[]}
def _write(path: Path, envelope: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data=json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    fd,tmp=tempfile.mkstemp(dir=path.parent, prefix=path.name+".", suffix=".tmp")
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
        directory_flag=getattr(os, "O_DIRECTORY", None)
        if directory_flag is not None:
            try:
                dfd=os.open(path.parent, directory_flag)
            except OSError:
                dfd=None
            if dfd is not None:
                try:
                    try:
                        os.fsync(dfd)
                    except OSError:
                        pass
                finally:
                    try:
                        os.close(dfd)
                    except OSError:
                        pass
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def _encrypt(payload: dict[str, Any], key: bytes, salt: bytes) -> dict[str, Any]:
    nonce=os.urandom(12); ct=AESGCM(key).encrypt(nonce, json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), _aad())
    return {"format":FORMAT,"version":VERSION,"kdf":KDF,"salt":_b64(salt),"encryption":"AESGCM","nonce":_b64(nonce),"ciphertext":_b64(ct)}
def _decrypt(envelope: dict[str, Any], password: str) -> tuple[dict[str, Any], bytes]:
    try:
        if envelope["format"] != FORMAT or envelope["version"] != VERSION: raise KeyError
        salt=_ub64(envelope["salt"]); key=derive(password,salt)
        pt=AESGCM(key).decrypt(_ub64(envelope["nonce"]), _ub64(envelope["ciphertext"]), _aad())
        return json.loads(pt.decode("utf-8")), key
    except Exception as exc: raise VaultAuthError() from exc
class Vault:
    def __init__(self, path: Path): self.path=path; self.payload: dict[str, Any] | None=None; self.session: VaultSession | None=None; self.pending_attestations: dict[str, AttestationProposal]={}; self.pending_revisions: dict[str, AnalysisRevisionProposal]={}
    def initialize(self, owner_name: str, password: str) -> VaultSession:
        if self.path.exists(): raise VaultAlreadyExistsError()
        if not owner_name.strip(): raise ValidationError()
        if not password.strip(): raise ValidationError()
        payload=empty_payload(owner_name); salt=os.urandom(16); key=derive(password,salt); _write(self.path,_encrypt(payload,key,salt)); self.payload=payload
        return self._session(key)
    def unlock(self, password: str) -> VaultSession:
        try:
            envelope = json.loads(self.path.read_text("utf-8"))
        except Exception as exc:
            raise VaultAuthError() from exc
        payload,key=_decrypt(envelope, password); self.payload=payload; return self._session(key)
    def _session(self, key: bytes) -> VaultSession:
        assert self.payload
        if self.session:
            for i in range(len(self.session.key_buffer)): self.session.key_buffer[i]=0
            self.session.unlocked=False
        self.pending_attestations.clear(); self.pending_revisions.clear()
        s=VaultSession(self.payload["owner"]["actor_id"], self.payload["vault_id"], "SES-"+uuid.uuid4().hex, True, bytearray(key)); self.session=s; return s
    def require(self) -> VaultSession:
        if not self.session or not self.session.unlocked or self.payload is None: raise VaultLockedError()
        return self.session
    def lock(self) -> None:
        if self.session:
            for i in range(len(self.session.key_buffer)): self.session.key_buffer[i]=0
            self.session.unlocked=False
        self.pending_attestations.clear(); self.pending_revisions.clear(); self.payload=None
    def persist(self) -> None:
        s=self.require(); env=json.loads(self.path.read_text("utf-8")); salt=_ub64(env["salt"]); _write(self.path,_encrypt(self.payload, bytes(s.key_buffer), salt))
    def propose_attestation(self, statement: str, supersedes: str | None=None) -> AttestationProposal:
        session=self.require()
        p=AttestationProposal(proposal_id="PROP-"+uuid.uuid4().hex, statement=statement, session_id=session.session_id, created_at=utc_now(), channel="text", supersedes_evidence_id=supersedes)
        self.pending_attestations[p.proposal_id]=p; return p
    def confirm_attestation(self, proposal_id: str) -> AuthenticatedUserAttestation:
        session=self.require()
        p=self.pending_attestations.get(proposal_id)
        if p is None or p.session_id != session.session_id: raise ValidationError()
        owner=self.payload["owner"]; eid="EV-UA-"+uuid.uuid4().hex
        existing={a["evidence_id"]:a for a in self.payload["attestations"]}
        if p.supersedes_evidence_id:
            if p.supersedes_evidence_id not in existing or any(a.get("supersedes_evidence_id")==p.supersedes_evidence_id for a in existing.values()): raise ValidationError()
        a=AuthenticatedUserAttestation(eid, owner["actor_id"], owner["display_name"], utc_now(), "text", p.statement, p.supersedes_evidence_id)
        self.payload["attestations"].append(a.__dict__); self.payload["audit_events"].append(AuditEvent("AUD-"+uuid.uuid4().hex,"attestation_committed",owner["actor_id"],utc_now(),eid,True).__dict__); self.persist()
        del self.pending_attestations[proposal_id]; return a
    def save_initial_analysis(self, saved: SavedAnalysis) -> None:
        """Transactionally persist a complete retained analysis:
        1. serialize the retained unit and re-validate the exact bytes that would be
           persisted, so a latent serialization defect fails before anything is written;
        2. build a copy-on-write candidate payload (the current payload is never mutated);
        3. encrypt and atomically write the candidate;
        4. only after the write succeeds, publish the candidate as the active payload.
        Any failure at any step leaves the previous payload and encrypted file untouched."""
        session=self.require()
        record=saved_analysis_to_payload(saved)
        saved_analysis_from_payload(record)
        candidate=dict(self.payload)
        candidate["saved_analyses"]=list(self.payload["saved_analyses"])+[record]
        env=json.loads(self.path.read_text("utf-8")); salt=_ub64(env["salt"])
        _write(self.path,_encrypt(candidate, bytes(session.key_buffer), salt))
        self.payload=candidate
    def save_approved_source_scope(self, scope: ApprovedSourceScope) -> None:
        """Transactionally persist a validated human-approved source scope."""
        session=self.require()
        record=approved_scope_to_payload(scope)
        approved_scope_from_payload(record)
        candidate=dict(self.payload)
        candidate["approved_source_scopes"]=list(self.payload.get("approved_source_scopes", []))+[record]
        env=json.loads(self.path.read_text("utf-8")); salt=_ub64(env["salt"])
        _write(self.path,_encrypt(candidate, bytes(session.key_buffer), salt))
        self.payload=candidate
