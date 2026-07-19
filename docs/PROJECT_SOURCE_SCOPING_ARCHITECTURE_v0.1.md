# Project Source Scoping v0.1 — architecture

The module is split into narrow responsibilities:

- `domain.py`: immutable result and review models;
- `provider.py`: dedicated provider protocol;
- `validator.py`: the sole canonical semantic validator;
- `prompts.py`: frozen prompt and strict response schema;
- `openai_provider.py`: network adapter only;
- `fake_provider.py`: generic deterministic test double;
- `service.py`: atomic provider invocation followed by validation;
- `review.py`: mandatory human resolution and evidence-snapshot binding;
- `serialization.py`: strict encrypted-persistence representation;
- `io.py`: neutral JSON workspace loader;
- `cli.py`: standalone demonstration entry point.

The dependency direction is inward: adapters depend on domain and validator; domain never imports Bridge, vault, desktop, or provider SDKs.

The reference fake provider is intentionally generic. It identifies explicit project anchors, extracts distinctive dates, codes, actors, and content tokens, then propagates contextual association through a graph. It is useful for deterministic tests and offline demonstrations, not a substitute for semantic production classification.

The production OpenAI provider receives the immutable target, neutral metadata, and authoritative spans. It does not receive ground truth or downstream analysis. Strict schema constrains shape; the local validator remains authoritative for identity, ownership, ordering, graph reachability, and partition invariants.

The integration seam is an approved scope, not raw provider output. Bridge may expose separate scope, review, and analyze commands. Existing analysis remains backward compatible when source scoping has not been started. Once scoping starts, downstream analysis must remain blocked until review is complete.
