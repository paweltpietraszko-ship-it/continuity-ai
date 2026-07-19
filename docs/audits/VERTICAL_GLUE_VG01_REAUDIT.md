# Vertical Glue VG-01 — niezależny re-audyt naprawy

## Zakres i rewizje

- Base: `bddcc936af71a723793e185ad06499eef534f774`.
- Fix: `fc7afe9c9517a963d48f846d5469aac06de3fe13`.
- Pierwotny audit: `f8ec47acecdd01aa7e308c6ee1e4374afe5cbbf0`.
- Re-audyt wykonano na dokładnym commicie Fix, przed dodaniem wyłącznie testów i tego raportu.
- Kod produkcyjny nie został zmodyfikowany.
- Niezależny dowód wykonawczy: `tests/audit_vertical_glue_reaudit/test_vg01_reaudit.py`.

## Werdykt

**FAIL — VERTICAL GLUE STILL BLOCKED: hook walidatora może zwrócić nową wartość niespełniającą pierwotnego JSON Schema, a controller publikuje ją jako sukces bez ponownej walidacji kontraktu.**

## Blocker — validator return value poszerza wcześniej zwalidowany kontrakt

Severity: blocker.

Controller najpierw waliduje `process.final_response` przez `_validated_output` i ustawia `structured_valid = True` (`src/continuity_ai/codex_session.py:1382-1385`). Następnie wynik może zostać zastąpiony dowolną wartością zwróconą przez `structured_output_validator` (`src/continuity_ai/codex_session.py:1399-1401`). Ta nowa wartość nie przechodzi ponownie przez pierwotne JSON Schema. Flaga `structured_valid` pozostaje prawdziwa, receipt zostaje utworzony z `structured_output_valid=True` (`src/continuity_ai/codex_session.py:1439`), a success state jest commitowany (`src/continuity_ai/codex_session.py:1469-1484`).

Obowiązkowy dodatkowy test zaczyna od schema-valid `{"answer": "schema-valid"}` przy schemacie wymagającym niepustego stringa. Hook zwraca nową wartość `{"answer": 7}`. Controller obecnie:

- zwraca schema-invalid wartość jako `CodexOperationResult.structured_output`;
- publikuje `receipt.succeeded == True` i `structured_output_valid == True`;
- przechodzi z `READY` do `INVESTIGATING`;
- zachowuje zwrócony Codex ID;
- utrwala receipt jako `last_successful_invocation_receipt`.

Reprodukcja znajduje się w `test_blocker_validator_return_value_can_widen_schema_and_commit_success`. Test świadomie charakteryzuje istniejące zachowanie blokujące i przechodzi tylko dlatego, że potwierdza publikację niepoprawnego sukcesu.

Kontrakt opisany w komentarzu `CodexOperationRequest` mówi, że hook nie może poszerzać wyniku już zaakceptowanego przez JSON Schema. Implementacja tego nie wymusza. Zamknięcie wymaga co najmniej ponownej walidacji wartości zwróconej przez hook względem pierwotnego schematu przed utworzeniem successful receipt i przed zmianą fazy/retencją ID, albo kontraktu hooka, który nie pozwala zastępować wartości.

## Wyniki wymaganych weryfikacji

| # | Wynik | Dowód |
|---|---|---|
| 1 | PASS | Schema-valid, semantycznie błędny payload odrzucony wyjątkiem validatora kończy się `INVALID_OUTPUT`; receipt jest failure, persisted phase pozostaje `READY`, retained Codex ID pozostaje `None`, active operation jest wyczyszczona i nie powstaje successful receipt. |
| 2 | PASS | Po takim odrzuceniu ponowne `start_investigation` na tym samym controller session ID przechodzi; retry reporting po analogicznym odrzuceniu również przechodzi. |
| 3 | PASS | Odrzucenie podczas reporting zachowuje wcześniejszy `last_successful_invocation_receipt`, zapisując osobno późniejszy failed `last_invocation_receipt`. |
| 4 | PASS | Dla JSON zgodnego składniowo, ale łamiącego schema (`answer` jako integer), semantic validator nie jest wywoływany. |
| 5 | PASS | Publiczny `InvalidCodexOutput` nie zawiera wyjątku validatora przez `__cause__`, `__context__`, `args`, receipt, reprezentację retained session ani surowy persisted JSON. |
| 6 | PASS | Focused i pełny backend potwierdzają CAS, wspólny CAS recovery/save, active-operation cleanup, blokadę równoległej operacji oraz controller/Codex session mismatch bez regresji. |
| 7 | PASS | Instrumentowany przepływ `CodexSourceScopingProvider` → `run_source_scoping` potwierdza kolejność dwóch wywołań kanonicznego validatora: pre-commit controller gate, następnie niezależny service pass. |
| 8 | PASS | Wszystkie trzy testy `live_network` przechodzą, w tym pełny mixed-to-approved vertical flow i oba testy zachowania/resume realnej sesji lokalnego Codex. |
| dodatkowy | **FAIL / blocker** | Hook zwraca nową schema-invalid wartość, którą controller publikuje jako sukces. |

## Regresje CAS, cleanup i mismatch

Poza nowymi testami re-audytu pełna macierz wykonała istniejące niezależne przypadki, między innymi:

- `test_stale_session_revision_is_rejected_without_durable_change`;
- `test_recovery_and_normal_save_share_one_revision_cas`;
- `test_second_simultaneous_operation_is_rejected`;
- `test_reporting_returned_id_mismatch_fails_closed`;
- `test_controller_session_id_mismatch_is_rejected`.

Wszystkie przeszły. Nowe testy dodatkowo sprawdzają wyczyszczenie `codex_process_active` i `active_operation` zarówno po schema rejection, jak i semantic rejection.

## Weryfikacja wykonawcza

- Focused: `uv run pytest -q tests/audit_vertical_glue_reaudit tests/audit_vertical_glue tests/integration/test_mixed_to_approved_vertical_flow.py tests/test_codex_session.py tests/approved_workspace tests/source_scoping -m "not live_network"` — **202 passed, 3 skipped, 1 deselected**.
- Pełny backend bez live: `uv run pytest -q -m "not live_network"` — **562 passed, 5 skipped, 3 deselected**.
- Wszystkie live: `uv run pytest -q -m live_network --force-enable-socket` — **3 passed, 567 deselected**.
- Compile: `uv run python -m compileall -q src tests` — **PASS**.
- `git diff --check` — **PASS**.

## Konkluzja

Naprawa domyka pierwotny VG-01 dla validatora, który odrzuca przez wyjątek: controller nie publikuje sukcesu, zachowuje retriable phase, sanitizuje wyjątek i utrzymuje receipt/lifecycle invariants. Nie domyka jednak granicy dla validatora, który zwraca przekształcony wynik. Ponieważ ten hook może obecnie poszerzyć pierwotny JSON Schema contract i opublikować niezgodną wartość jako sukces, Vertical Glue nie może jeszcze zostać zatwierdzony do Bridge wiring.

**FAIL — VERTICAL GLUE STILL BLOCKED: hook walidatora może zwrócić nową wartość niespełniającą pierwotnego JSON Schema, a controller publikuje ją jako sukces bez ponownej walidacji kontraktu.**
