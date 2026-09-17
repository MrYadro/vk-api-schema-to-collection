# Реестр форматов: многовидовой экспорт с точкой расширения

Дата: 2026-09-17
Статус: утверждённый дизайн (подход A — `FormatSpec`-объекты)

## Контекст и цель

Проект вырос с одного формата экспорта до пяти (`tree`, `bundled`, `postman`,
`postman-v3`, `openapi`). Добавление формата сегодня требует правок в 4+ местах:
ветка в `main()` со своим print, `default_out_path`, функции где-то в
1123-строчном `generate_collection.py`, плюс опционально `merge_collection`
(fmt-цепочки), `validate_collection` (сниффинг + валидатор), CI-упаковка и README.

Цель — реестр форматов как единая точка правды: генерация, merge и валидация
описываются одним контрактом; новый формат = один модуль в `formats/` + одна
строка регистрации. Внешний контракт CLI (флаги, формат вывода, коды возврата)
не меняется.

## Область

Реструктуризация `generate_collection.py` (ядро + 4 формата) и `validate_collection.py`
(сниффинг + валидаторы), перенос merge-загрузчиков из `merge_collection.py` в
модули форматов, миграция тестов на новые импорты. `fetch_parameter_descriptions.py`
не затрагивается. CI-workflow не меняется (вызывает CLI, чей контракт стабилен).

## Структура файлов

```
core.py                     общее ядро (~700 строк)
formats/__init__.py         FormatSpec + FORMATS (реестр)
formats/opencollection.py   tree + bundled (две спеки, один модуль)
formats/postman.py          Postman v2.1
formats/postman_v3.py       Postman Native Git (V3)
formats/openapi.py          OpenAPI 3.1
generate_collection.py      тонкий CLI
merge_collection.py         чистый merge моделей
validate_collection.py      тонкий валидатор CLI
```

Граф импортов строго вниз, циклов нет:

- `core.py` — ни от кого не зависит (stdlib; ленивый `require_yaml()` переезжает сюда из `merge_collection`).
- `formats/*` → `core`, `merge_collection` (модельный merge и хелперы `_norm_name`/`_keep_index`).
- `generate_collection.py`, `validate_collection.py` → `formats` (+ `core`).
- `merge_collection.py` → `core` (только `require_yaml`); НЕ знает имён форматов.

`core.py` получает из текущего `generate_collection.py`: `load_methods_file`,
`RefResolver`, `collect_methods`, YAML-эмиттер (`scalar`/`fmt`/`key`/
`block_scalar`/`emit`/`to_yaml`), `visible_enum`/`enum_walk`/
`param_enum_values`, `get_latest_api_version`/`resolve_api_version`,
`fix_bullets`, `load_descriptions`, `param_description`/`method_description`,
`form_rows`, `md_cell`, `method_docs`, `build_request`, `TESTS_SCRIPT`,
`DOCS_MD`, `meta_request`/`meta_folder`, `build`, `SAFE_FILENAME`,
`MULTI_UNDERSCORE`, `TRANSLIT`, `unique_filename`, `SCRIPT_DIR`,
`default_schema_dir`, `is_public`, `first_sentence`, `require_yaml` (новый).

## Контракт FormatSpec (`formats/__init__.py`)

`@dataclasses.dataclass(frozen=True)`:

| Поле | Тип | Назначение |
| --- | --- | --- |
| `name` | str | ключ реестра, значение `--format` |
| `default_out` | str | путь по умолчанию для `default_out_path` |
| `stats_keys` | tuple[str, ...] | специфика формата в print (модельные: `folders`,`requests`; openapi: `operations`,`schemas`) |
| `model_based` | bool | payload — модель коллекции (разрешает `--dump-json` и merge) |
| `build` | callable(ctx) -> (payload, stats) | модельные спеки делят один закэшированный `core.build(ctx)`; openapi — свой `build_openapi` |
| `write` | callable(payload, out) -> (file_count, note) | вся запись формата; `note` — суффикс print («+N environment file(s)») |
| `supports_merge` | bool | разрешает `--merge`/`--prune` |
| `load_existing` | callable(out) -> collection \| None | загрузчик существующего вывода (merge-форматы) |
| `prune_orphans` | callable(out, collection) -> list[Path] \| None | удаление файлов-сирот |
| `keep_old_items` | bool = True | False только у `postman-v3` (частичная модель) |
| `matches` | callable(path) -> bool | сниффинг для валидатора |
| `validate` | callable(path, schema_override=None) | валидация; ленивые импорты yaml/jsonschema/urllib |

`BuildContext` (dataclass в `formats/__init__.py`): `schema_dir`, `api_version`,
`name`, `descriptions`, `include_all`. Кэш модельного build — `functools.lru_cache`
по параметрам контекста, чтобы модельные спеки не перестраивали коллекцию.

`FORMATS: dict[str, FormatSpec]` — явная регистрация в `formats/__init__.py`,
по одной строке на формат. Порядок ключей — только для перечисления в `--format`
и сообщений; порядок сниффинга валидатора задаётся отдельно (см. «Валидация»).

## Унифицированный CLI (`generate_collection.py`)

`main()` без форматных if/elif:

1. `--format` choices из `FORMATS`; `--merge/--prune` при `not spec.supports_merge` → `parser.error` (текст действующий: `--merge/--prune are only supported for tree, bundled and postman-v3`; имена merge-форматов берутся из реестра, формулировка сохраняется).
2. `payload, stats = spec.build(ctx)`.
3. `--merge`: `old = spec.load_existing(out)`; если не None — `merge_collection.merge(payload, old, prune=..., keep_old_items=spec.keep_old_items)`.
4. `--dump-json` при `spec.model_based`.
5. `file_count, note = spec.write(payload, out)`; mkdir — ответственность `write`.
6. `--prune`: `spec.prune_orphans(out, payload)`.
7. Единый print: `format=… {stats_keys}… files=… collisions=… encodings=… ru_descriptions=… out=…{note} ({size}){merge-extra}{pruned_files}`. Размер считает CLI: файл — размер файла, каталог — сумма `rglob`. Строка вывода байт-в-байт совпадает с текущей для каждого формата (закрепляется golden-тестом).

`default_out_path(fmt)` остаётся функцией-обёрткой над реестром (используется
тестами). Ленивый `import merge_collection` в main сохраняется (генерация без
merge-флагов не тянет pyyaml-зависимости — как сегодня).

## Перенос форматного кода

- `formats/opencollection.py`: `write_tree`, `unique_filename`+`TRANSLIT`
  (используются только tree), `load_tree`, `load_bundled` (из
  `merge_collection`), tree-prune (из `merge_collection.prune_orphans`),
  bundled-write (mkdir + `to_yaml({**collection, "bundled": True})` из main),
  `TREE_SPEC`, `BUNDLED_SPEC`.
- `formats/postman.py`: `POSTMAN_SCHEMA_URL`, `POSTMAN_NAMESPACE`,
  `POSTMAN_TEST_SCRIPT`, `postman_id`, `postman_param`, `postman_request`,
  `postman_folder`, `to_postman`, `POSTMAN_ENVIRONMENT_COLOR`,
  `to_postman_environment`, `dump_postman`, `dump_postman_environment`,
  `postman_environment_path`, write-ветка из main (коллекция + env-файлы).
- `formats/postman_v3.py`: `POSTMAN_V3_KIND_*`, `postman_v3_*`, `write_postman_v3`,
  `POSTMAN_V3_UNSAFE_FILENAME`, `load_postman_v3`, v3-prune.
- `formats/openapi.py`: `OPENAPI_*`, `register_component`, `openapi_schema`,
  `openapi_param_property`, `openapi_responses`, `openapi_operation`,
  `build_openapi`, write (mkdir + `to_yaml`).

`merge_collection.py` после переноса: `merge`, `_merge_variables`,
`_merge_rows`, `_protect_slots`, `_merge_request`, `_merge_folder`,
`_norm_name`, `V3_UNSAFE`, `_keep_index`; `require_yaml` — из `core`.
Юнит-тесты merge не меняются (API `merge()` неизменен).

## Валидация

Валидаторы переезжают в модули форматов (ленивые импорты `yaml`, `jsonschema`,
`urllib.request` — генерационный путь остаётся stdlib). Сниффинг — единая
точка правды в `FormatSpec.matches`; приоритет проверки задаётся явно
(константа-кортеж в `validate_collection.py`, не порядок реестра):

1. `openapi`: имя оканчивается на `.openapi.yaml` или родитель `openapi`.
2. `postman`: имя содержит `postman_collection`/`postman_environment` и `.json`.
3. `postman-v3`: каталог, содержащий `postman/collections/`.
4. `bundled`: файл `.yaml`/`.yml`.
5. `tree`: каталог (fallback — как сегодня «opencollection»).

Спека `postman` внутри `validate` различает collection/environment по имени
файла; env-валидация сохраняет текущее поведение SKIP при недоступности
онлайн-схемы (403). `--schema` (локальная схема) передаётся только в
opencollection-валидатор.

`validate_collection.py`: перебор `FORMATS` по `matches()` → вызов
`spec.validate(path, schema_override)`; печать OK/SKIP-строк — прежняя.
`pick_format(path)` сохраняется как совместимая обёртка: сниффинг через
реестр + карта легаси-имён (`tree`/`bundled` → `opencollection`, `postman` →
`postman-collection`/`postman-environment` по имени файла) — текущие тесты
`pick_format` остаются в силе без правок ассертов.

## Тесты

Существующие файлы сохраняют имена; импорты мигрируют на `core` /
`formats.*` (решение пользователя — совместимый re-export слой не создаётся):

- `test_generate_collection.py`: `to_postman`/`postman_*` → `formats.postman`;
  `postman_v3_*` → `formats.postman_v3`; `write_tree`/`unique_filename` →
  `formats.opencollection`; `build*`/`to_yaml`/схемные хелперы → `core`;
  `main`-тесты (если есть) — `generate_collection` без изменений.
- `test_merge_collection.py`: merge-юниты — без изменений; тесты загрузчиков —
  `formats.opencollection.load_tree/load_bundled`, `formats.postman_v3.load_postman_v3`
  (частичная модель); `run_main`/mini-schema — без изменений.
- `test_validate_collection.py`: `pick_format`/`validate_postman_v3` — из
  `validate_collection` (обёртки) и/или `formats.postman_v3` — ассерты не меняются.

Новые тесты контракта реестра (`test_formats_registry.py`):

- `FORMATS` содержит ровно 5 форматов с корректными `default_out`;
- у merge-форматов заполнены `load_existing`/`prune_orphans`, у остальных — нет;
- `--merge` на не-merge формате → `SystemExit` с текстом ошибки;
- golden: для каждого формата строка print `main()` содержит все `stats_keys`,
  `files=`, `out=`, `(size)` (формат вывода стабилен);
- `matches` различает все 6 валидационных целей (tree dir, bundled yaml,
  collection json, environment json, v3 dir, openapi yaml).

## Документация

- README: таблица «Скрипты» упоминает `core.py`/`formats/`; новый мини-раздел
  «Как добавить формат» (модуль в `formats/` с `FormatSpec` + строка регистрации
  + `stats_keys`/`write`/`matches`/`validate`; merge — опционально).
- `AGENTS.md` в корне репо: конвенция коммитов `feat:`/`fix:`/`docs:`/`chore:`/`refactor:`
  (решение пользователя из этой сессии).

## Совместимость и риски

- CLI-контракт (флаги, вывод, коды) неизменен — CI и релизный конвейер не
  замечают рефакторинг; закреплено golden-тестом print.
- Сниффинг и поведение валидаторов переносятся 1:1 (включая SKIP env-схемы);
  тесты `pick_format` не меняются.
- `merge()`-API не меняется; e2e-тесты merge через `run_main` остаются.
- Главный объём — механическая миграция ~1100 строк тестов; риск ложных
  перемещений снижается пофайловым прогоном suites после каждой задачи.
- `generate_collection.py` после рефакторинга — только CLI (argparse + п.1-7);
  `__main__`-блок сохраняется.

## Не входит

- Изменение форматов вывода, спек форматов, merge-правил.
- Авто-обнаружение плагинов (pkgutil и т.п.).
- Правки `fetch_parameter_descriptions.py`, CI-workflow, релизного процесса.
- Перевод README на английский и прочие доки-расширения.
