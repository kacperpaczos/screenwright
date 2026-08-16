# Architecture

screenwright is organized around 5 **bounded contexts** (DDD):

```
domains/
├── corpus/         Korpus screenshotów — pobieranie ze źródeł, indeks, ID
├── capture/        Bezgłowe przechwytywanie (Xvfb + Xlib + ImageMagick)
├── override/       Nadpisanie katalogu AppStream
├── matrix/         Matryca VM — orkiestracja golden image, drivers, builders
└── verification/   Walidacja screenshotów (template match)

shared/            Shared kernel: types, ports, http, hashing, results, settings
cli/               Adaptery argparse → domeny
```

## Dependency rules

1. `domains/*` mogą importować wyłącznie z `shared/`.
2. `shared/` nie importuje z `domains/`.
3. `cli/` importuje wiele domen (jedyne miejsce w architekturze).
4. Domeny komunikują się przez porty (`Protocol`) z `shared/ports.py` lub przez
   argumenty wywołań funkcji, nie przez współdzielone typy wewnętrzne.

Reguły są enforce'owane przez:

- `tests/architecture/test_boundaries.py` — AST walk sprawdzający importy.
- `.import-linter.ini` — kontrakty dla `import-linter` CLI.

W CI job `architecture` jest `continue-on-error: true` (Faza 0–3), w Faza 4 → required.

## Typy domenowe (pydantic v2)

Każda domena ma `models.py` z modelami pydantic v2:

- `frozen=True` i `extra="forbid"` — każdy model jest niemutowalny i odrzuca
  nieznane pola.
- Walidacja na granicach I/O (HTTP response, CLI argv, plik JSON).
- W hot path (parsowanie `fedora.xml.gz` z tysiącami komponentów) — używamy
  `shared.pydantic_utils.construct_validated()` z `sample_rate=100`: pełna
  walidacja co 100-ty wpis, `model_construct` dla reszty.

## Przepływ danych

```
CLI args → Pydantic model (StrictSpec) → domena X
            ↓
        wykonanie z portami (Protocol) z shared/ports.py
            ↓
        wynik: dict lub model pydantic → JSON Schema → zapis
```

## Porty (Protocol)

W `shared/ports.py` zdefiniowane są wspólne porty:

- `SourceFetcher`, `IndexStorage` — używane przez corpus
- `Reporter` — używane przez matrix/verification
- `StoreDriver`, `LibvirtBackend` — używane przez matrix

Domeny definiują swoje własne porty w `domains/<name>/ports.py`:

- `CorpusSource`, `CorpusStorage` — corpus
- `DisplayBackend`, `WindowDiscovery`, `FrameGrabber` — capture
- `CatalogLoader`, `ComponentFinder` — override
- `DistroBuilder`, `StoreDriver`, `ReporterSink` — matrix
- `TemplateMatcher`, `Reporter` — verification

Adaptery (implementacje) są w `domains/<name>/{adapters,backend,drivers,distro_builders}/`.

## Konwencje

- **Brandowane typy** (`shared/types.py`): `AppId`, `ComponentId`, `PkgName`,
  `SnapName`, `Sha256`, `HttpUrl`, `RelativePath`. Dzięki temu `mypy` odróżnia
  `AppId` od `ComponentId` (częsty błąd w starym kodzie).
- **Ścieżki** zawsze `Path`, nigdy `str`. Walidacja `RelativePath` (bez
  bezwzględnych ścieżek w plikach wyjściowych).
- **Log entry** z `shared.logging.log_entry` — JSON w stderr, parsowalny.
- **Brak komentarzy** (zasada projektu — kod ma być samodokumentujący się).