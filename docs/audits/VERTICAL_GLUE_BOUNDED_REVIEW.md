# Vertical Glue — bounded review

## Zakres

- Audytowana delta: `ed7e401cd88bd20c612c172272ed2d5aab8140cc..bddcc936af71a723793e185ad06499eef534f774`.
- Review wykonano na `bddcc936af71a723793e185ad06499eef534f774`.
- Kod produkcyjny nie został zmodyfikowany.
- Dodany dowód wykonawczy: `tests/audit_vertical_glue/test_semantic_rejection_boundary.py`.

## Werdykt

**FAIL — VERTICAL GLUE BLOCKED: semantyczne odrzucenie payloadu Source Scoping następuje po commicie sukcesu controllera, pozostawiając tę samą sesję w nieretrywalnym `INVESTIGATING` z pozornie udanym receipt.**

## Blocker VG-01 — commit sukcesu przed walidacją semantyczną

Severity: blocker.

`CodexSourceScopingProvider.classify` wywołuje `controller.start_investigation` i zwraca jego `structured_output` (`src/continuity_ai/integration/codex_source_scoping_provider.py:79-98`). Controller sprawdza wyłącznie przekazany JSON Schema, po czym utrwala `phase=INVESTIGATING`, `last_invocation_receipt` oraz `last_successful_invocation_receipt` jako sukces i czyści active-operation (`src/continuity_ai/codex_session.py:1444-1455`). Dopiero po powrocie providera `run_source_scoping` wywołuje kanoniczny `validate_source_scoping_payload` (`src/continuity_ai/source_scoping/service.py:11-30`).

Reprodukcja zwraca z zasymulowanego procesu Codex JSON zgodny ze schematem controllera, ale z podmienionym `target_project`. Pole nadal spełnia schema (`string`, `minLength: 1`), natomiast kanoniczny validator poprawnie odrzuca je względem autorytatywnego targetu.

Po odrzuceniu zaobserwowano:

- wyjątek `ValidationError` wraca przed human review;
- żaden krok human review, approval, materializacji, bindingu ani reportingu nie jest wywołany;
- destination workspace nie powstaje;
- persisted phase pozostaje `investigating`;
- `last_invocation_receipt.succeeded == True`;
- `last_successful_invocation_receipt.succeeded == True`;
- `codex_process_active == False` i `active_operation is None`;
- ponowne `start_investigation` dla tego samego controller session ID jest odrzucane przez `InvalidSessionState`, ponieważ investigation dopuszcza wyłącznie fazę `READY` (`src/continuity_ai/codex_session.py:957-968`);
- normalny caller pipeline nie otrzymuje `InvestigationOutcome`, a więc nie otrzymuje też utworzonego wewnątrz session ID potrzebnego do jawnej operacji kończącej. Niskopoziomowe `complete_session` istnieje, ale nie jest wynikiem ani automatyczną kompensacją tej ścieżki i nie usuwa fałszywego successful receipt.

Dowód jest utrwalony w `tests/audit_vertical_glue/test_semantic_rejection_boundary.py:82-172`. Test przechodzi, ponieważ świadomie asercyjnie zapisuje bieżące zachowanie blokujące; nie jest testem oczekiwanego fixa.

## Wyniki sprawdzenia inwariantów

| # | Wynik | Ustalenie |
|---|---|---|
| 1 | PASS | Mixed workspace i approved-only workspace używają jednego zachowanego `codex_session_id`; testy scripted i live potwierdzają tę samą wartość po zmianie `cwd`. |
| 2 | PASS | Reporting wymaga `APPROVED`, retained Codex ID i approved root; zawsze przekazuje ten ID jako resume. Mismatch nie zastępuje ID ani nie przechodzi do kolejnej sesji. |
| 3 | PASS | Nowy Codex Source Scoping provider nie zawiera ścieżki fallback do OpenAI ani fake. `CodexSessionError` jest mapowany na `ProviderError`. Import z `openai_provider` służy wyłącznie współdzielonemu serializerowi requestu i nie uruchamia providera OpenAI. |
| 4 | FAIL | `validate_source_scoping_payload` nadal jest kanonicznym walidatorem i poprawnie odrzuca payload, lecz vertical glue wywołuje go po trwałym commicie sukcesu controllera. Odrzucenie nie jest częścią atomowej granicy lifecycle/receipt. |
| 5 | PASS | `_codex_schema` nie zmienia wejściowego schematu, a wynik dla bieżącego Source Scoping schema różni się wyłącznie usunięciem `maxLength`; niezależny test porównuje pełną strukturę. |
| 6 | PASS z blockerem stanu | Błędy materializacji, stale evidence, mismatch Codex ID oraz zmiana pliku/workspace zatrzymują późniejsze kroki. Krytyczne semantic rejection także nie dociera do human review ani materializacji, ale pozostawia błędny stan controllera opisany w VG-01. |
| 7 | FAIL na granicy glue | Bazowy controller zachowuje CAS, parę active marker/operation, cleanup i fail-closed proces boundary; pełne regresje przechodzą. End-to-end receipt semantics nie są jednak zachowane dla semantycznego odrzucenia, bo receipt został już opublikowany jako sukces. |

## Dodatkowe obserwacje bez blockera

- Reporting używa approved workspace bindingu i `resume_session_id=session.codex_session_id` (`src/continuity_ai/codex_session.py:1011-1043`).
- Pipeline jest sekwencyjny: human review, approval, materialization i reporting występują dopiero po zwróceniu poprawnego `InvestigationOutcome` (`src/continuity_ai/integration/mixed_to_approved_pipeline.py:85-96`). To poprawnie zapobiega downstream execution w reprodukcji VG-01.
- CAS nadal porównuje revision przed zapisem (`src/continuity_ai/codex_session.py:315-345`), a krytyczna reprodukcja potwierdza spójne wyczyszczenie active-operation. Problem dotyczy miejsca semantycznego commitu, nie mechanizmu CAS.

## Weryfikacja

- Focused: `uv run pytest -q tests/audit_vertical_glue tests/integration/test_mixed_to_approved_vertical_flow.py tests/test_codex_session.py tests/approved_workspace tests/source_scoping -m "not live_network"` — **193 passed, 3 skipped, 1 deselected**.
- Pełny backend bez live: `uv run pytest -q` — **553 passed, 5 skipped, 3 deselected**.
- Wszystkie istniejące live tests: `uv run pytest -q -m live_network --force-enable-socket` — **3 passed, 558 deselected**.
- Compile: `uv run python -m compileall -q src tests` — **PASS**.
- `git diff --check` — **PASS**.

## Konkluzja

Przepływ prawidłowo utrzymuje jeden prawdziwy Codex session ID i approved-only root, a jego późniejsze guardy zatrzymują naruszenia. Nie może jednak zostać podłączony do Bridge, dopóki wynik semantycznej walidacji Source Scoping nie stanie się częścią atomowej granicy sukcesu/failure controllera albo równoważnej jawnej kompensacji, która nie pozostawia `INVESTIGATING` i successful receipt po odrzuceniu.

**FAIL — VERTICAL GLUE BLOCKED: semantyczne odrzucenie payloadu Source Scoping następuje po commicie sukcesu controllera, pozostawiając tę samą sesję w nieretrywalnym `INVESTIGATING` z pozornie udanym receipt.**
