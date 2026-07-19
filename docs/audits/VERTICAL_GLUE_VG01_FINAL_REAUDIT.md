# Vertical Glue VG-01 — finalny niezależny re-audyt delty

## Zakres i rewizje

- Base: `fc7afe9c9517a963d48f846d5469aac06de3fe13`.
- Fix: `ff1ca167986596d7676e971cd680bd5d43ee6277`.
- Poprzedni re-audyt: `16f3645b84efddde8bfce0952ea966d345a65236`.
- Re-audyt rozpoczęto na `HEAD == Fix`; rodzicem Fix jest dokładnie Base.
- Poprzedni re-audyt nie jest przodkiem bieżącej gałęzi
  (`git merge-base --is-ancestor ...` zwrócił `1`), a jego commit nie został
  cherry-picknięty.
- Audyt obejmuje wyłącznie deltę Base–Fix: dwa pliki produkcyjne, jeden test
  naprawy oraz korektę istniejącego testu kontraktu validatora.
- Kod produkcyjny nie został zmodyfikowany podczas re-audytu. Nowy niezależny
  dowód wykonawczy znajduje się wyłącznie w
  `tests/audit_vertical_glue_final/test_vg01_final_reaudit.py`.

## Werdykt

**PASS — VG-01 CLOSED; VERTICAL GLUE APPROVED FOR BRIDGE WIRING**

Nie znaleziono blockera ani regresji w audytowanej delcie. Naprawa domyka
wcześniejszą możliwość poszerzenia kontraktu przez wartość zwrotną validatora:
hook jest runtime-only i rejection-only, dostaje głęboką kopię, a kontroler
publikuje wyłącznie pierwotny obiekt zaakceptowany przez JSON Schema.

## Ustalenia z inspekcji delty

1. `CodexOperationRequest.structured_output_validator` ma kontrakt
   `Callable[[object], None] | None` (`codex_session.py:258`). Nie jest
   serializowany do stanu sesji.
2. Po produkcyjnej walidacji JSON Schema hook otrzymuje
   `copy.deepcopy(structured)` (`codex_session.py:1411-1413`).
3. Każdy rezultat inny niż `None` ustawia `INVALID_OUTPUT`, zeruje
   `structured_valid` i usuwa wartość przeznaczoną do publikacji
   (`codex_session.py:1419-1422`). Wyjątek hooka trafia do tej samej
   sanitizowanej ścieżki failure.
4. Oryginalna zmienna `structured` nie jest przypisywana wynikiem hooka.
   Success state jest utrwalany dopiero po wszystkich bramkach, a
   `CodexOperationResult` publikuje ten sam obiekt (`codex_session.py:1479-1501`).
5. Source Scoping zachowuje dwie osobne bramki kanoniczne: providerową przed
   success commit (`codex_source_scoping_provider.py:101-102`) oraz serwisową
   po zwrocie providera (`source_scoping/service.py:30`).

## Macierz wymaganych weryfikacji

| # | Wynik | Dowód |
|---|---|---|
| 1 | PASS | Akceptacja następuje wyłącznie po zwrocie dokładnie `None`; test sukcesu sprawdza również success receipt i przejście fazy. |
| 2 | PASS | `False`, `0`, pusty string, pusta lista, pusty słownik, argument validatora oraz odmienny schema-valid obiekt kończą się `INVALID_OUTPUT`. |
| 3 | PASS | Instrumentacja wyniku `_validated_output` dowodzi innej tożsamości argumentu validatora na poziomie root, zagnieżdżonego słownika, listy i wewnętrznego słownika. |
| 4 | PASS | Validator zmienia element listy, dopisuje element, usuwa wymagane pole, dodaje pole zagnieżdżone i top-level; opublikowany wynik pozostaje bajtowo/strukturalnie zgodny z pierwotnym JSON. |
| 5 | PASS | Test tożsamości potwierdza `result.structured_output is schema_validated[0]`: publikowany jest dokładnie pierwotny obiekt zwrócony przez realną walidację JSON Schema. Osobny test potwierdza, że schema-invalid output nie uruchamia hooka. |
| 6 | PASS | Sekret umieszczony w message i zagnieżdżonych `ValueError.args` jest nieobecny w publicznych `args`, `receipt`, `repr(session)` i persisted JSON; `__cause__` oraz `__context__` są `None`. |
| 7 | PASS | Po rejection faza pozostaje `READY`, retained Codex ID pozostaje `None`, nie ma successful receipt, active operation jest wyczyszczona, a retry na tym samym controller session przechodzi. |
| 8 | PASS | Odrzucenie podczas reporting zachowuje wcześniejszy successful receipt i fazę `APPROVED`, zapisuje osobny failed receipt oraz pozwala na reporting retry. |
| 9 | PASS | Instrumentowany pełny przepływ rejestruje dokładnie `controller`, potem `service`; oba canonical passes dostają obiekty o różnych tożsamościach. |
| 10 | PASS | Focused suite obejmuje stale-revision CAS, session-local CAS, recovery/save shared CAS, concurrent recovery CAS, cleanup, genuine same-session reporting resume oraz controller/Codex ID mismatch. Wszystkie przechodzą. |
| 11 | PASS | Końcowy wspólny przebieg wszystkich trzech istniejących testów `live_network`: `3 passed`. |

## Obowiązkowe próby zachowania validatora

Nowy zestaw testów wykonuje wszystkie wskazane próby:

- zmiana zagnieżdżonego obiektu in-place, w tym elementu i długości listy;
- usunięcie zagnieżdżonego wymaganego pola;
- dodanie zagnieżdżonego oraz top-level pola;
- zwrot schema-valid, ale innego obiektu;
- zwrot argumentu otrzymanego przez validator;
- zwrot false-like wartości innych niż `None`: `False`, `0`, `""`, `[]`, `{}`;
- wyjątek zawierający sekret w message i zagnieżdżonych args;
- poprawna akceptacja przez niejawny/jawny zwrot `None`.

Plik audytowy zawiera 12 przypadków pytest (w tym pięć wariantów
parametryzowanych false-like) i przeszedł samodzielnie: `12 passed`.

## Regresje lifecycle, CAS, resume i mismatch

Focused suite wykonał zarówno nowe próby, jak i istniejące testy kontraktowe,
w szczególności:

- `test_stale_session_revision_is_rejected_without_durable_change`;
- `test_unrelated_session_survives_session_local_cas`;
- `test_recovery_and_normal_save_share_one_revision_cas`;
- `test_two_concurrent_recoveries_cannot_both_succeed`;
- `test_independent_controllers_share_atomic_recovery_cas`;
- `test_reporting_resumes_the_genuine_investigation_session_id`;
- `test_reporting_returned_id_mismatch_fails_closed`;
- `test_controller_session_id_mismatch_is_rejected`;
- `test_no_replacement_session_on_reporting_id_mismatch`.

Wszystkie przeszły. Nowe testy dodatkowo kontrolują `codex_process_active ==
False` i `active_operation is None` po wczesnym oraz późnym odrzuceniu.

## Weryfikacja wykonawcza

- Nowe testy audytowe:
  `uv run pytest -q tests/audit_vertical_glue_final/test_vg01_final_reaudit.py`
  — **12 passed**.
- Focused:
  `uv run pytest -q tests/audit_vertical_glue_final tests/audit_vertical_glue_reaudit tests/audit_vertical_glue tests/test_codex_session.py tests/audit_codex_session tests/integration/test_mixed_to_approved_vertical_flow.py tests/approved_workspace tests/source_scoping -m "not live_network"`
  — **235 passed, 3 skipped, 1 deselected**.
- Pełny backend bez live:
  `uv run pytest -q -m "not live_network"`
  — **574 passed, 5 skipped, 3 deselected**.
- Wszystkie live, końcowy wspólny przebieg:
  `uv run pytest -q -m live_network --force-enable-socket`
  — **3 passed, 579 deselected**.
- `uv run python -m compileall -q src tests` — **PASS**.
- `git diff --check` — **PASS**.

### Obserwacja z live runów

Pierwszy wspólny live run zakończył się `2 passed, 1 failed`, ponieważ realny
Codex zwrócił ten sam poprawny zestaw ścieżek z separatorami Windows `\\`, a
test oczekiwał URI z `/`. Nie była to różnica zawartości ani regresja audytowanej
delty. Izolowany rerun tego przypadku przeszedł (`1 passed`), po czym końcowy
wspólny rerun wszystkich trzech testów przeszedł (`3 passed`). Istniejących
testów nie zmieniano.

## Konkluzja

Delta wymusza zamknięty kontrakt validatora zarówno dla wyjątków, zwrotu
argumentu, arbitralnego nowego obiektu, jak i wszystkich false-like wartości
innych niż `None`. Głęboka kopia odcina mutacje na każdym sprawdzonym poziomie,
success publikuje dokładnie obiekt zwalidowany przez JSON Schema, a failure
path zachowuje sanitizację, retry, receipt history, CAS i tożsamość sesji.

**PASS — VG-01 CLOSED; VERTICAL GLUE APPROVED FOR BRIDGE WIRING**
