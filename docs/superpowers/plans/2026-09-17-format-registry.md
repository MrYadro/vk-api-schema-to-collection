# Format Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реестр форматов `formats/` (FormatSpec: генерация + merge + валидация) как единая точка расширения; CLI без форматных веток; тесты на новых импортах.

**Architecture:** Общее ядро → `core.py`; каждый формат — модуль в `formats/` со спекой; `generate_collection.py`/`validate_collection.py` — тонкие CLI над реестром; `merge_collection.py` — чистый merge моделей. Порядок задач сохраняет suite зелёным после каждой: сначала ядро, затем форматные модули (main делегирует им ветки), затем merge-перенос, затем унификация CLI и валидатора.

**Tech Stack:** Python 3 stdlib; PyYAML/jsonschema — ленивые импорты в валидации/merge (как сегодня).

**Spec:** `docs/superpowers/specs/2026-09-17-format-registry-design.md`

## Global Constraints

- Генерация без merge-флагов — stdlib-only; `yaml`/`jsonschema`/`urllib.request` — только ленивые импорты внутри валидаторов/загрузчиков.
- Внешний CLI-контракт неизменен: флаги, строка вывода (байт-в-байт на формат), коды возврата; CI-workflow не меняется.
- `merge(new, old, prune=False, keep_old_items=True) -> (collection, stats)` — API не меняется; юнит-тесты merge не правятся.
- Совместимого re-export слоя НЕ делаем: тесты мигрируют на `core`/`formats.*` (решение пользователя). `import generate_collection as g` в тестах остаётся только для `g.main`/CLI-функций.
- Без комментариев в коде (кроме `# noqa`).
- Коммиты — conventional: `refactor:`, `test:`, `docs:`, `chore:`, `feat:`.
- Тестовый раннер: `python3 -m unittest discover -p "test_*.py"` из корня репо; текущий базовый счёт — 84 (перед началом).

---

### Task 1: `core.py` — извлечение общего ядра

**Files:**
- Create: `core.py`
- Modify: `generate_collection.py`, `merge_collection.py`, `test_generate_collection.py`, `test_merge_collection.py`

**Interfaces:**
- Produces: модуль `core` с перечисленными ниже именами (сигнатуры не меняются, тела переносятся как есть); `core.require_yaml()` — бывший `merge_collection._require_yaml` (message тот же: `--merge/--prune need PyYAML: pip install pyyaml`).

- [ ] **Step 1: Create core.py (move, не copy)**

Перенести из `generate_collection.py` (тела без изменений):

```
load_methods_file, RefResolver, collect_methods,
scalar, fmt, key, block_scalar, emit, to_yaml,
visible_enum, enum_walk, param_enum_values,
ANON_TOKEN_URL, LAST_VERSION_URL, get_latest_api_version, resolve_api_version,
BULLET_LINE, fix_bullets, load_descriptions, param_description, method_description,
form_rows, md_cell, method_docs, build_request, TESTS_SCRIPT, DOCS_MD,
meta_request, meta_folder, build,
SAFE_FILENAME, MULTI_UNDERSCORE, _CYR, _LAT, TRANSLIT, unique_filename,
SCRIPT_DIR, default_schema_dir, is_public, first_sentence
```

Плюс импорты, которые этим функциям нужны (`json`, `os`, `pathlib`, `re`, `sys`, `urllib.request`).

Из `validate_collection.py` перенести общие валидационные хелперы (ленивые импорты уже внутри):

```
OC_SCHEMA_URL, POSTMAN_COLLECTION_SCHEMA_URL, POSTMAN_ENVIRONMENT_SCHEMA_URL,
OPENAPI_SCHEMA_URL, load_schema, load_document, jsonschema_validator, allow_postman_secret_type
```

Добавить в `core.py`:

```python
def require_yaml():
    try:
        import yaml
    except ImportError:
        raise SystemExit("--merge/--prune need PyYAML: pip install pyyaml")
    return yaml
```

- [ ] **Step 2: Rewire generate_collection.py / merge_collection.py**

- `generate_collection.py`: удалить перенесённые определения; наверху `from core import (<все имена, которые использует оставшийся код: build, build_openapi остался в g, to_yaml, write-хелперы форматов, resolve_api_version, default_schema_dir, SCRIPT_DIR, SAFE_FILENAME, TESTS_SCRIPT, DOCS_MD и т.д.>)`. Форматный код и `main()` пока остаются в `g`.
- `merge_collection.py`: удалить `_require_yaml`; `from core import require_yaml`; вызовы `_require_yaml()` → `require_yaml()`.

- [ ] **Step 3: Migrate test imports (только core-имена)**

В `test_generate_collection.py` и `test_merge_collection.py` заменить обращения `g.<имя>` → `core.<имя>` для каждого имени из списка Step 1, добавить `import core`. `g.` остаётся только для ещё живых в `g` форматных имён (`to_postman`, `postman_*`, `write_tree`, `postman_v3_*`, `build_openapi`, `main`, `dump_postman`, `write_postman_v3`, `unique_filename` — уходит в этой задаче, см. список) и `v.`/`m.` без изменений. Проверка полноты:

```bash
python3 - <<'EOF'
import generate_collection as g
core_names = ["to_yaml","build","build_request","collect_methods","TRANSLIT","unique_filename","is_public","load_descriptions","method_docs","form_rows"]
print([n for n in core_names if hasattr(g, n)])
EOF
```

Expected: `[...]` — непустой список допустим (from-import в g для собственного использования), но в тестах `g.to_yaml`/`g.unique_filename`/`g.TRANSLIT` встречаться больше не должны:

```bash
grep -n "g\.to_yaml\|g\.unique_filename\|g\.TRANSLIT\|g\.build(" test_*.py
```

Expected: пусто.

- [ ] **Step 4: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py"`
Expected: 84 test, OK

- [ ] **Step 5: Commit**

```bash
git add core.py generate_collection.py merge_collection.py test_generate_collection.py test_merge_collection.py
git commit -m "refactor: extract shared core (schema loading, yaml emitter, model build, validation helpers) into core.py"
```

---

### Task 2: `formats/postman.py` — Postman v2.1

**Files:**
- Create: `formats/__init__.py` (пустой пакет)
- Create: `formats/postman.py`
- Modify: `generate_collection.py` (ветка postman), `test_generate_collection.py`

**Interfaces:**
- Consumes: `core` (Task 1).
- Produces: `formats.postman` с перенесёнными `to_postman`, `dump_postman`, `dump_postman_environment`, `to_postman_environment`, `postman_environment_path`, `postman_id`, `postman_param`, `postman_request`, `postman_folder`, константы `POSTMAN_*`; новые `write_postman(collection, out) -> (file_count, note)`, `matches(path) -> bool`, `validate(path, schema_override=None)`.

- [ ] **Step 1: Create package + module**

`formats/__init__.py` — пустой файл. `formats/postman.py`: перенести из `generate_collection.py` блок 559-675 (`POSTMAN_SCHEMA_URL`, `POSTMAN_NAMESPACE`, `POSTMAN_TEST_SCRIPT`, `postman_id`, `postman_param`, `postman_request`, `postman_folder`, `to_postman`, `POSTMAN_ENVIRONMENT_COLOR`, `to_postman_environment`, `dump_postman`, `dump_postman_environment`, `postman_environment_path`) и из `validate_collection.py` — `validate_postman_collection`, `validate_postman_environment` (импортируют `load_document`, `jsonschema_validator`, `allow_postman_secret_type`, `load_schema`, `POSTMAN_COLLECTION_SCHEMA_URL`, `POSTMAN_ENVIRONMENT_SCHEMA_URL` из `core`). Добавить:

```python
def write_postman(collection, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_postman(collection), encoding="utf-8")
    env_paths = []
    for i, env in enumerate(collection.get("config", {}).get("environments", [])):
        if i == 0:
            env_path = postman_environment_path(out)
        else:
            env_path = out.parent / f"{SAFE_FILENAME.sub('_', env['name'])}.postman_environment.json"
        env_path.write_text(dump_postman_environment(env), encoding="utf-8")
        env_paths.append(env_path)
    note = f" +{len(env_paths)} environment file(s)" if env_paths else ""
    return 1 + len(env_paths), note


def matches(path):
    name = pathlib.Path(path).name
    return name.endswith(".json") and ("postman_collection" in name or "postman_environment" in name)


def validate(path, schema_override=None):
    name = pathlib.Path(path).name
    if "postman_environment" in name:
        try:
            schema = core.load_schema(None, core.POSTMAN_ENVIRONMENT_SCHEMA_URL)
        except OSError:
            print(f"SKIP: postman environment schema unavailable online ({core.POSTMAN_ENVIRONMENT_SCHEMA_URL}), validation skipped")
            return None
        _, values = validate_postman_environment(path, schema)
        return 0, values
    schema = core.allow_postman_secret_type(core.load_schema(None, core.POSTMAN_COLLECTION_SCHEMA_URL))
    return validate_postman_collection(path, schema)
```

(`from core import SAFE_FILENAME` наверху; печать OK-строк остаётся в `validate_collection.py` — `validate` возвращает кортежи счётчиков.)

- [ ] **Step 2: Delegate main-ветку**

В `generate_collection.py` ветка `elif args.format == "postman":` → `file_count, note = postman.write_postman(collection, args.out)` + `size` как сегодня; убрать дублированный env-код. Импорт: `from formats import postman`.

- [ ] **Step 3: Migrate tests**

`test_generate_collection.py`: все `g.to_postman`/`g.postman_*`/`g.dump_postman*` → `postman.*` (`from formats import postman`).

```bash
grep -n "g\.to_postman\|g\.postman\|g\.dump_postman" test_*.py
```

Expected: пусто.

- [ ] **Step 4: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py"`
Expected: 84 test, OK

- [ ] **Step 5: Commit**

```bash
git add formats/ generate_collection.py test_generate_collection.py
git commit -m "refactor: postman v2.1 emitters, writer and validators into formats/postman.py"
```

---

### Task 3: `formats/postman_v3.py` — Postman Native Git

**Files:**
- Create: `formats/postman_v3.py`
- Modify: `generate_collection.py` (ветка postman-v3), `test_generate_collection.py`, `test_validate_collection.py`

**Interfaces:**
- Consumes: `core` (Task 1).
- Produces: `formats.postman_v3` с `POSTMAN_V3_KIND_*`, `postman_v3_auth_id`, `postman_v3_definition`, `postman_v3_folder_definition`, `postman_v3_request`, `postman_v3_environment`, `POSTMAN_V3_UNSAFE_FILENAME`, `write_postman_v3`; валидационные `matches(path)`, `validate(path, schema_override=None)` (бывший `validate_postman_v3` — имя сохранить как алиас).

- [ ] **Step 1: Create module**

Перенести из `generate_collection.py` строки 898-1016; из `validate_collection.py` — `validate_postman_v3` (ленивый `import yaml` внутри уже есть). Добавить:

```python
def matches(path):
    path = pathlib.Path(path)
    return path.is_dir() and (path / "postman" / "collections").is_dir()


def validate(path, schema_override=None):
    return validate_postman_v3(path)
```

- [ ] **Step 2: Delegate main-ветку**

Ветка `elif args.format == "postman-v3":` → `file_count = postman_v3.write_postman_v3(collection, args.out)`; импорт `from formats import postman_v3`.

- [ ] **Step 3: Migrate tests**

- `test_generate_collection.py`: `g.postman_v3_*`/`g.write_postman_v3` → `postman_v3.*`.
- `test_validate_collection.py`: `from generate_collection import write_postman_v3` → `from formats.postman_v3 import write_postman_v3`; `v.validate_postman_v3(out)` → `postman_v3.validate(out)`.

```bash
grep -n "g\.postman_v3\|g\.write_postman_v3\|v\.validate_postman_v3\|from generate_collection import write_postman_v3" test_*.py
```

Expected: пусто.

- [ ] **Step 4: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py"`
Expected: 84 test, OK

- [ ] **Step 5: Commit**

```bash
git add formats/postman_v3.py generate_collection.py test_generate_collection.py test_validate_collection.py
git commit -m "refactor: postman v3 emitters, writer and structural validator into formats/postman_v3.py"
```

---

### Task 4: `formats/openapi.py` — OpenAPI 3.1

**Files:**
- Create: `formats/openapi.py`
- Modify: `generate_collection.py` (ветка openapi), `test_generate_collection.py`

**Interfaces:**
- Consumes: `core` (Task 1).
- Produces: `formats.openapi` с `OPENAPI_SPEC_VERSION`, `OPENAPI_DESCRIPTION`, `VK_ERROR_SCHEMA`, `OPENAPI_STRIP_KEYS`, `register_component`, `openapi_schema`, `openapi_param_property`, `openapi_responses`, `openapi_operation`, `build_openapi`; новые `write_openapi(doc, out) -> (1, "")`, `matches(path)`, `validate(path, schema_override=None)`.

- [ ] **Step 1: Create module**

Перенести из `generate_collection.py` строки 703-895; из `validate_collection.py` — `validate_openapi`. Добавить:

```python
def write_openapi(doc, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_yaml(doc), encoding="utf-8")
    return 1, ""


def matches(path):
    path = pathlib.Path(path)
    return path.name.endswith(".openapi.yaml") or path.parent.name == "openapi"


def validate(path, schema_override=None):
    schema = core.load_schema(schema_override, core.OPENAPI_SCHEMA_URL)
    return validate_openapi(path, schema)
```

- [ ] **Step 2: Delegate main-ветку**

Ветка `if args.format == "openapi":` (ранний return) → собрать `doc, stats = openapi.build_openapi(...)`; `file_count, note = openapi.write_openapi(doc, args.out)`; print оставить в ветке как есть (note пока не используется — унификация в Task 7).

- [ ] **Step 3: Migrate tests**

`test_generate_collection.py` (класс `TestBuildOpenapi` и соседи): `g.build_openapi`/`g.openapi_*`/`g.register_component`/`g.VK_ERROR_SCHEMA` → `openapi.*`.

```bash
grep -n "g\.build_openapi\|g\.openapi\|g\.register_component\|g\.VK_ERROR_SCHEMA\|g\.OPENAPI" test_*.py
```

Expected: пусто.

- [ ] **Step 4: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py"`
Expected: 84 test, OK

- [ ] **Step 5: Commit**

```bash
git add formats/openapi.py generate_collection.py test_generate_collection.py
git commit -m "refactor: openapi builder, writer and validator into formats/openapi.py"
```

---

### Task 5: `formats/__init__.py` — FormatSpec + реестр + `formats/opencollection.py`

**Files:**
- Modify: `formats/__init__.py`
- Create: `formats/opencollection.py`
- Modify: `generate_collection.py` (ветки tree/bundled), `test_generate_collection.py`

**Interfaces:**
- Consumes: `core.build` (Task 1).
- Produces:
  - `formats.FormatSpec` (dataclass, поля по спеке: `name, default_out, stats_keys, model_based, build, write, supports_merge=False, load_existing=None, prune_orphans=None, keep_old_items=True, matches=None, validate=None`)
  - `formats.BuildContext(schema_dir, api_version, name, descriptions, include_all)` — frozen dataclass
  - `formats.build_collection(ctx) -> (collection, stats)` — `functools.lru_cache`-обёртка над `core.build` (ctx хэшируем: все поля — Path/str/bool)
  - `formats.FORMATS: dict[str, FormatSpec]` — 5 записей
  - `formats.opencollection`: `write_tree`, `unique_filename`, `TRANSLIT`, `MULTI_UNDERSCORE`, `_CYR`, `_LAT` (перенос из `core`/`g`; `SAFE_FILENAME` остаётся в `core` — нужен postman), `write_bundled(collection, out) -> (1, "")`, спеки `TREE_SPEC`, `BUNDLED_SPEC`.

- [ ] **Step 1: Write the failing test (контракт реестра — минимальный; полный в Task 9)**

Создать `test_formats_registry.py`:

```python
import unittest

from formats import FORMATS, FormatSpec


class TestRegistry(unittest.TestCase):
    def test_five_formats_registered(self):
        self.assertEqual(
            sorted(FORMATS),
            ["bundled", "openapi", "postman", "postman-v3", "tree"],
        )

    def test_default_out_paths(self):
        self.assertEqual(FORMATS["tree"].default_out, "dist/opencollection/vk-api")
        self.assertEqual(FORMATS["bundled"].default_out, "dist/opencollection/vk-api.yaml")
        self.assertEqual(FORMATS["postman"].default_out, "dist/postman/vk-api.postman_collection.json")
        self.assertEqual(FORMATS["postman-v3"].default_out, "dist/postman/vk-api-local")
        self.assertEqual(FORMATS["openapi"].default_out, "dist/openapi/vk-api.yaml")

    def test_stats_keys(self):
        self.assertEqual(FORMATS["tree"].stats_keys, ("folders", "requests"))
        self.assertEqual(FORMATS["openapi"].stats_keys, ("operations", "schemas"))

    def test_model_based_flags(self):
        for name in ("tree", "bundled", "postman", "postman-v3"):
            self.assertTrue(FORMATS[name].model_based, name)
        self.assertFalse(FORMATS["openapi"].model_based)
```

Run: `python3 -m unittest test_formats_registry -v` — Expected: FAIL (нет `formats.FormatSpec`).

- [ ] **Step 2: Implement registry + opencollection module**

`formats/__init__.py`:

```python
import dataclasses
import functools

from core import build as _core_build


@dataclasses.dataclass(frozen=True)
class BuildContext:
    schema_dir: object
    api_version: str
    name: str
    descriptions: object
    include_all: bool


@dataclasses.dataclass(frozen=True)
class FormatSpec:
    name: str
    default_out: str
    stats_keys: tuple
    model_based: bool
    build: object
    write: object
    supports_merge: bool = False
    load_existing: object = None
    prune_orphans: object = None
    keep_old_items: bool = True
    matches: object = None
    validate: object = None


@functools.lru_cache(maxsize=None)
def build_collection(ctx):
    return _core_build(ctx.schema_dir, ctx.api_version, ctx.name, ctx.descriptions, ctx.include_all)


from formats import openapi as _openapi
from formats import opencollection as _opencollection
from formats import postman as _postman
from formats import postman_v3 as _postman_v3

FORMATS = {
    "tree": _opencollection.TREE_SPEC,
    "bundled": _opencollection.BUNDLED_SPEC,
    "postman": _postman.POSTMAN_SPEC,
    "postman-v3": _postman_v3.POSTMAN_V3_SPEC,
    "openapi": _openapi.OPENAPI_SPEC,
}
```

`formats/opencollection.py`: перенести `write_tree`, `unique_filename`, `TRANSLIT`, `MULTI_UNDERSCORE`, `_CYR`, `_LAT` (из `core`/`g` — после переноса из `core` удалить; `unique_filename` использует `SAFE_FILENAME` → `from core import SAFE_FILENAME, to_yaml`); добавить:

```python
def write_bundled(collection, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_yaml({**collection, "bundled": True}), encoding="utf-8")
    return 1, ""


def _tree_write(collection, out):
    return write_tree(collection, out), ""


def _bundled_write(collection, out):
    return write_bundled(collection, out)


TREE_SPEC = FormatSpec(
    name="tree",
    default_out="dist/opencollection/vk-api",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=_tree_write,
)
BUNDLED_SPEC = FormatSpec(
    name="bundled",
    default_out="dist/opencollection/vk-api.yaml",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=_bundled_write,
)
```

(`build_collection` импортируется из `formats` — цикл? `formats/__init__` импортирует `formats.opencollection`, а тот импортирует `from formats import FormatSpec, build_collection` — это работает: на момент исполнения тела `formats.opencollection` имена уже определены в частично-инициализированном `formats`. Проверить прогоном; при проблеме — спеки собирать функцией `register()` в `__init__` после определений.)

Спеки в `formats/postman.py`, `formats/postman_v3.py`, `formats/openapi.py` (добавить в каждый модуль):

```python
POSTMAN_SPEC = FormatSpec(
    name="postman",
    default_out="dist/postman/vk-api.postman_collection.json",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_postman,
    matches=matches,
    validate=validate,
)
```

```python
POSTMAN_V3_SPEC = FormatSpec(
    name="postman-v3",
    default_out="dist/postman/vk-api-local",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=lambda collection, out: (write_postman_v3(collection, out), ""),
    matches=matches,
    validate=validate,
)
```

```python
OPENAPI_SPEC = FormatSpec(
    name="openapi",
    default_out="dist/openapi/vk-api.yaml",
    stats_keys=("operations", "schemas"),
    model_based=False,
    build=lambda ctx: openapi_build(ctx.schema_dir, ctx.api_version, ctx.name, ctx.descriptions, ctx.include_all),
    write=write_openapi,
    matches=matches,
    validate=validate,
)
```

(в `formats/openapi.py` переименовать локальную ссылку на перенесённый `build_openapi` при конфликте имён с импортом; в `formats/postman_v3.py` — `write` как обычная функция `def _write(collection, out): return write_postman_v3(collection, out), ""`, без lambda, для единообразия.)

- [ ] **Step 3: Delegate main-ветки tree/bundled**

Ветка `else:` (tree) → `file_count, _ = opencollection.write_tree-обёртка` (использовать `_opencollection._tree_write`); ветка `bundled` → `write_bundled`. Импорт `from formats import opencollection`.

- [ ] **Step 4: Migrate tests + run**

`test_generate_collection.py`: `g.write_tree` → `opencollection.write_tree`. Run: `python3 -m unittest discover -p "test_*.py"` — Expected: 88 (84 + 4 новых registry), OK. `grep -n "g\.write_tree" test_*.py` — пусто.

- [ ] **Step 5: Commit**

```bash
git add formats/ generate_collection.py test_generate_collection.py test_formats_registry.py core.py
git commit -m "refactor: FormatSpec registry in formats/ with opencollection tree+bundled specs; all five formats registered"
```

---

### Task 6: Merge за реестром — перенос loaders/prune

**Files:**
- Modify: `formats/opencollection.py`, `formats/postman_v3.py`, `formats/__init__.py` (спеки), `generate_collection.py` (merge-блок), `merge_collection.py`
- Test: `test_merge_collection.py`

**Interfaces:**
- Consumes: `merge_collection` (`merge`, `_norm_name`, `_keep_index`, `V3_UNSAFE`) — остаются там.
- Produces: `formats.opencollection.load_tree/load_bundled/tree_prune_orphans`; `formats.postman_v3.load_postman_v3/v3_prune_orphans`; спеки заполняют `supports_merge=True, load_existing=..., prune_orphans=..., keep_old_items=...`; из `merge_collection.py` удаляются `load_bundled`, `load_tree`, `load_postman_v3`, `load_existing`, `prune_orphans` (остаётся модельное ядро).

- [ ] **Step 1: Move loaders + prune (тела без изменений)**

- `load_bundled`, `load_tree` → `formats/opencollection.py` (импорт `from core import require_yaml`).
- `load_postman_v3` → `formats/postman_v3.py`.
- `prune_orphans` разбирается: tree-ветка → `formats/opencollection.tree_prune_orphans(out_path, collection)`; v3-ветка → `formats/postman_v3.v3_prune_orphans(out_path, collection)`; общий преамбул-код `_keep_index`/`_norm_name` — `from merge_collection import _keep_index, _norm_name`.
- Спеки: `TREE_SPEC`/`BUNDLED_SPEC`/`POSTMAN_V3_SPEC` получают `supports_merge=True, load_existing=<функция>, prune_orphans=<функция>`, у v3 `keep_old_items=False`.

- [ ] **Step 2: Rewire main merge-блок**

```python
    merge_stats = None
    if args.merge:
        import merge_collection
        old = None
        loader = spec.load_existing if spec.supports_merge else None
        if loader is not None:
            old = loader(args.out)
        if old is not None:
            collection, merge_stats = merge_collection.merge(
                collection, old, prune=args.prune, keep_old_items=spec.keep_old_items
            )
```

(spека `spec = FORMATS[args.format]` — временная локальная переменная в `main()` до унификации Task 7.) Prune-блок: `pruned_files = spec.prune_orphans(args.out, collection) if args.prune and spec.prune_orphans else []`.

- [ ] **Step 3: Migrate loader/prune tests**

`test_merge_collection.py`: `m.load_tree` → `opencollection.load_tree`, `m.load_bundled` → `opencollection.load_bundled`, `m.load_postman_v3` → `postman_v3.load_postman_v3`, `m.prune_orphans(out, "tree", ...)` → `opencollection.tree_prune_orphans(out, ...)`, `m.prune_orphans(out, "postman-v3", ...)` → `postman_v3.v3_prune_orphans(out, ...)`, `m.load_existing(path, fmt)` — удалить/заменить прямой проверкой спек (`FORMATS["bundled"].load_existing(path)`); тест `test_bundled_noop` удаляется (нет общей prune_orphans). Merge-юниты и run_main-тесты — без изменений.

- [ ] **Step 4: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py"`
Expected: 88 - 1 (bundled_noop удалён) = 87, OK

- [ ] **Step 5: Commit**

```bash
git add formats/ generate_collection.py merge_collection.py test_merge_collection.py
git commit -m "refactor: merge loaders and prune moved into format modules; specs own merge support; merge_collection stays pure model merge"
```

---

### Task 7: Унифицированный `main()` + golden print

**Files:**
- Modify: `generate_collection.py` (полная перезапись `main()` + `default_out_path`)
- Test: `test_merge_collection.py` (golden-тесты)

**Interfaces:**
- Consumes: `FORMATS`, `FormatSpec`, `BuildContext`, `build_collection` (Tasks 5-6).
- Produces: `main()` без форматных веток; `default_out_path(fmt)` — обёртка над `FORMATS[fmt].default_out`.

- [ ] **Step 1: Write the failing golden test**

В `test_merge_collection.py` добавить (переиспользуя `write_mini_schema`/`run_main`; для openapi — фикстуру как в `TestBuildOpenapi`: `MINI_SCHEMA` из `test_generate_collection.py`):

```python
from test_generate_collection import MINI_SCHEMA


class TestCliPrintGolden(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def run_and_capture(self, argv):
        import generate_collection as g
        from contextlib import redirect_stdout
        import io
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(sys, "argv", argv):
            g.main()
        return buf.getvalue()

    def test_tree_print_contains_contract_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            out = root / "out"
            line = self.run_and_capture(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.199"]).strip()
            self.assertIn("format=tree folders=", line)
            self.assertIn(" requests=", line)
            self.assertIn(" files=", line)
            self.assertIn(" collisions=0", line)
            self.assertIn(" ru_descriptions=", line)
            self.assertIn(f" out={out} (", line)
            self.assertTrue(line.endswith("MB)"), line)

    def test_bundled_and_v3_and_openapi_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            openapi_root = root / "oas"
            for rel, doc in MINI_SCHEMA.items():
                p = openapi_root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(doc), encoding="utf-8")
            cases = [
                (["--format", "bundled", "--out", str(root / "b.yaml"), "--schema-dir", str(schema)], "format=bundled folders=", " requests="),
                (["--format", "postman-v3", "--out", str(root / "v3"), "--schema-dir", str(schema)], "format=postman-v3 folders=", " requests="),
                (["--format", "postman", "--out", str(root / "p.json"), "--schema-dir", str(schema)], "format=postman folders=", " +1 environment file(s)"),
                (["--format", "openapi", "--out", str(root / "o.yaml"), "--schema-dir", str(openapi_root)], "format=openapi operations=", " schemas="),
            ]
            for argv, *needles in cases:
                with self.subTest(argv=argv[1]):
                    line = self.run_and_capture(["generate_collection.py", *argv, "--api-version", "5.199"]).strip()
                    for needle in needles:
                        self.assertIn(needle, line)
```

(Если `MINI_SCHEMA` в `test_generate_collection.py` не экспортирован на уровне модуля — он определён на уровне модуля, проверить grep; иначе поднять его определение на уровень модуля.)

Run: `python3 -m unittest test_merge_collection.TestCliPrintGolden -v` — Expected: PASS уже на старом main (контракт уже соблюдается) или FAIL на мелочах; зафиксировать фактическое поведение до переписывания — это цель golden: заморозить ДО refactor.

- [ ] **Step 2: Rewrite main()**

```python
def default_out_path(fmt):
    return pathlib.Path(FORMATS[fmt].default_out)


def main():
    parser = argparse.ArgumentParser(description="Generate OpenCollection collection from vk-api-schema")
    parser.add_argument("--schema-dir", default=None, type=pathlib.Path)
    parser.add_argument("--out", default=None, type=pathlib.Path)
    parser.add_argument("--format", choices=tuple(FORMATS), default="tree")
    parser.add_argument("--api-version", default="latest", help="API version, or 'latest' to fetch from dev portal")
    parser.add_argument("--name", default="VK API")
    parser.add_argument("--all", action="store_true", help="include nodoc/hidden methods (default: public only)")
    parser.add_argument("--descriptions", default=SCRIPT_DIR / "data/parameter_descriptions.json", help="RU descriptions cache from dev portal")
    parser.add_argument("--dump-json", type=pathlib.Path, help="also dump the built object as JSON for verification")
    parser.add_argument("--merge", action="store_true", help="update existing output instead of replacing (tree, bundled, postman-v3)")
    parser.add_argument("--prune", action="store_true", help="delete requests and folders absent from the new schema (tree, bundled, postman-v3)")
    args = parser.parse_args()
    spec = FORMATS[args.format]
    if args.schema_dir is None:
        args.schema_dir = default_schema_dir()
    if args.out is None:
        args.out = default_out_path(args.format)
    if (args.merge or args.prune) and not spec.supports_merge:
        parser.error("--merge/--prune are only supported for tree, bundled and postman-v3")
    ctx = BuildContext(
        schema_dir=args.schema_dir,
        api_version=resolve_api_version(args.api_version),
        name=args.name,
        descriptions=args.descriptions,
        include_all=args.all,
    )
    payload, stats = spec.build(ctx)
    merge_stats = None
    if args.merge and spec.load_existing is not None:
        import merge_collection
        old = spec.load_existing(args.out)
        if old is not None:
            payload, merge_stats = merge_collection.merge(
                payload, old, prune=args.prune, keep_old_items=spec.keep_old_items
            )
    if args.dump_json and spec.model_based:
        args.dump_json.parent.mkdir(parents=True, exist_ok=True)
        args.dump_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    file_count, note = spec.write(payload, args.out)
    if args.out.is_dir():
        total = sum(f.stat().st_size for f in args.out.rglob("*") if f.is_file())
    else:
        total = args.out.stat().st_size
    size = f"{total / 1024 / 1024:.1f} MB"
    pruned_files = []
    if args.prune and spec.prune_orphans is not None:
        pruned_files = spec.prune_orphans(args.out, payload)
    extra = ""
    if merge_stats is not None:
        extra += " " + " ".join(f"{k}={v}" for k, v in merge_stats.items())
    if pruned_files:
        extra += f" pruned_files={len(pruned_files)}"
    stat_bits = " ".join(f"{k}={stats[k]}" for k in spec.stats_keys)
    print(
        f"format={args.format} {stat_bits} "
        f"files={file_count} collisions={stats['collisions']} encodings={','.join(stats['encodings'])} "
        f"ru_descriptions={stats['ru_descriptions']} out={args.out}{note} ({size}){extra}"
    )
```

Импорты наверху `generate_collection.py`: `from formats import FORMATS, BuildContext` + `from core import resolve_api_version, default_schema_dir, SCRIPT_DIR`. Из `generate_collection.py` удалить все форматные функции и ветки (после Tasks 2-6 их там уже нет; здесь удаляются остатки: старые ветки, старый `default_out_path`-dict).

- [ ] **Step 3: Run full suite + golden**

Run: `python3 -m unittest discover -p "test_*.py"`
Expected: 87 + 2 golden = 89, OK; вывод e2e-тестов (`test_prune_without_merge…`, `test_tree_merge_integration…` и др.) визуально совпадает с прежним (asserts уже проверяют файлы; golden проверяет строки).

- [ ] **Step 4: Commit**

```bash
git add generate_collection.py test_merge_collection.py
git commit -m "refactor: registry-driven unified main() — no format branches, golden print tests lock CLI output"
```

---

### Task 8: `validate_collection.py` — тонкий CLI над реестром

**Files:**
- Modify: `validate_collection.py`, `formats/opencollection.py`
- Test: `test_validate_collection.py` (ассерты `pick_format` НЕ меняются)

**Interfaces:**
- Consumes: `FORMATS` + `spec.matches`/`spec.validate` (Tasks 2-6).
- Produces: `validate_collection.pick_format(path)` — обёртка с легаси-именами; `SNIFF_PRIORITY = ("openapi", "postman", "postman-v3", "bundled", "tree")`; opencollection-валидаторы `validate_bundled`/`validate_tree` переезжают в `formats/opencollection.py` (+ `matches` для tree/bundled).

- [ ] **Step 1: Add matches/validate to opencollection spec**

`formats/opencollection.py` — перенести из `validate_collection.py` `validate_bundled`, `validate_tree` (импорт хелперов из `core`) и добавить:

```python
def matches_tree(path):
    path = pathlib.Path(path)
    return path.is_dir() and not (path / "postman" / "collections").is_dir()


def matches_bundled(path):
    path = pathlib.Path(path)
    return not path.is_dir() and path.suffix in (".yaml", ".yml")
```

В спеки: `TREE_SPEC.matches = matches_tree` (через конструктор), `validate = lambda path, schema_override=None: validate_tree(path, core.load_schema(schema_override, core.OC_SCHEMA_URL))` — оформить обычной функцией `_validate_tree(path, schema_override=None)`; аналогично `_validate_bundled` для `BUNDLED_SPEC`.

- [ ] **Step 2: Rewrite validate_collection.py**

```python
#!/usr/bin/env python3
import argparse
import pathlib
import sys

from formats import FORMATS

SNIFF_PRIORITY = ("openapi", "postman", "postman-v3", "bundled", "tree")


def sniff_spec(path):
    for name in SNIFF_PRIORITY:
        spec = FORMATS[name]
        if spec.matches is not None and spec.matches(path):
            return spec
    return FORMATS["tree"]


def pick_format(path):
    spec = sniff_spec(path)
    if spec.name == "postman":
        name = pathlib.Path(path).name
        return "postman-environment" if "postman_environment" in name else "postman-collection"
    if spec.name in ("tree", "bundled"):
        return "opencollection"
    return spec.name


def main():
    parser = argparse.ArgumentParser(description="Validate a generated collection against its official JSON Schema")
    parser.add_argument("path", type=pathlib.Path, help="bundled .yaml, tree directory, or postman .json file")
    parser.add_argument("--schema", type=pathlib.Path, default=None, help="local schema override (opencollection)")
    args = parser.parse_args()
    spec = sniff_spec(args.path)
    if spec.name == "postman":
        name = args.path.name
        if "postman_environment" in name:
            res = spec.validate(args.path)
            if res is None:
                return None
            _, values = res
            print(f"OK: postman environment, {values} variables, 0 schema violations")
            return None
        folders, requests = spec.validate(args.path)
        print(f"OK: postman collection, {folders} folders, {requests} requests, 0 schema violations")
        return None
    if spec.name == "postman-v3":
        folders, requests = spec.validate(args.path)
        print(f"OK: postman v3 local, {folders} folders, {requests} requests, 0 structural violations")
        return None
    if spec.name == "openapi":
        paths, schemas = spec.validate(args.path)
        print(f"OK: openapi 3.1, {paths} paths, {schemas} schemas, 0 schema violations")
        return None
    folders, requests = spec.validate(args.path, args.schema)
    print(f"OK: {folders} folders, {requests} requests, 0 schema violations")
    return None


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run tests**

`python3 -m unittest test_validate_collection -v` — Expected: PASS (все 6 ассертов `pick_format` без изменений); full suite — OK.

- [ ] **Step 4: Commit**

```bash
git add validate_collection.py formats/opencollection.py
git commit -m "refactor: validate_collection sniffs format via registry matches with legacy pick_format aliases; opencollection validators in their format module"
```

---

### Task 9: Контрактные тесты реестра (полные)

**Files:**
- Test: `test_formats_registry.py`

**Interfaces:**
- Consumes: `FORMATS` (Tasks 5-8).

- [ ] **Step 1: Add contract tests**

Дополнить `test_formats_registry.py`:

```python
class TestMergeContract(unittest.TestCase):
    def test_merge_formats_have_loaders(self):
        for name, spec in FORMATS.items():
            if spec.supports_merge:
                self.assertIsNotNone(spec.load_existing, name)
                self.assertIsNotNone(spec.prune_orphans, name)
            else:
                self.assertIsNone(spec.load_existing, name)

    def test_merge_matrix(self):
        self.assertEqual(
            {n for n, s in FORMATS.items() if s.supports_merge},
            {"tree", "bundled", "postman-v3"},
        )
        self.assertFalse(FORMATS["postman-v3"].keep_old_items)
        self.assertTrue(FORMATS["tree"].keep_old_items)

    def test_merge_flag_rejected_for_postman_and_openapi(self):
        import generate_collection as g
        from unittest import mock
        import sys as _sys
        for fmt in ("postman", "openapi"):
            with self.subTest(fmt=fmt):
                with mock.patch.object(_sys, "argv", ["generate_collection.py", "--format", fmt, "--merge"]):
                    with self.assertRaises(SystemExit) as cm:
                        g.main()
                    self.assertEqual(cm.exception.code, 2)


class TestMatchesTargets(unittest.TestCase):
    def test_six_validation_targets(self):
        import pathlib
        from formats import FORMATS as F
        from validate_collection import sniff_spec
        self.assertEqual(sniff_spec(pathlib.Path("vk-api.postman_collection.json")).name, "postman")
        self.assertEqual(sniff_spec(pathlib.Path("vk-api.postman_environment.json")).name, "postman")
        self.assertEqual(sniff_spec(pathlib.Path("dist/openapi/vk-api.yaml")).name, "openapi")
        self.assertEqual(sniff_spec(pathlib.Path("vk-api.openapi.yaml")).name, "openapi")
        self.assertEqual(sniff_spec(pathlib.Path("vk-api.yaml")).name, "bundled")
        import tempfile
        import formats.postman_v3 as p3
        import generate_collection as g
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            from test_generate_collection import COLLECTION
            p3.write_postman_v3(COLLECTION, out)
            self.assertEqual(sniff_spec(out).name, "postman-v3")
            tree_out = pathlib.Path(tmp) / "tree"
            from formats import opencollection
            opencollection.write_tree(COLLECTION, tree_out)
            self.assertEqual(sniff_spec(tree_out).name, "tree")
```

- [ ] **Step 2: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py"`
Expected: 89 + 5 = 94 (примерно; точный счёт — все новые тесты + все старые), OK

- [ ] **Step 3: Commit**

```bash
git add test_formats_registry.py
git commit -m "test: format registry contract — merge matrix, CLI rejection, sniffing of all six validation targets"
```

---

### Task 10: README + AGENTS.md + финальный аудит

**Files:**
- Modify: `README.md`, Create: `AGENTS.md`

**Interfaces:**
- Consumes: всё.

- [ ] **Step 1: README**

В разделе «Скрипты» после таблицы добавить абзац и новый раздел перед «## Параметры запуска»:

```markdown
## Как добавить формат вывода

Форматы живут в `formats/` — по модулю на формат, каждый экспортирует `FormatSpec`:

1. Создайте `formats/<имя>.py`: функции `write(payload, out) -> (file_count, note)`,
   опционально `build(ctx)` (по умолчанию — общая модель коллекции через
   `formats.build_collection`), `matches(path)` и `validate(path)` для валидатора.
2. Зарегистрируйте спеку в `FORMATS` в `formats/__init__.py`.
3. Для поддержки `--merge`: `load_existing(out)` и `prune_orphans(out, collection)`
   в том же модуле плюс `supports_merge=True` (см. `formats/opencollection.py`).

`--format`, дефолтный путь вывода, сниффинг валидатора и статистика печати
подхватываются из реестра автоматически.
```

- [ ] **Step 2: AGENTS.md**

```markdown
# AGENTS.md

- Коммиты: conventional commits — `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.
- Код без комментариев (кроме `# noqa`); генерация — только stdlib, yaml/jsonschema — ленивые импорты.
- Тесты: `python3 -m unittest discover -p "test_*.py"` из корня репо.
```

- [ ] **Step 3: Final audit**

```bash
python3 -m unittest discover -p "test_*.py"
grep -rn "import generate_collection\|from generate_collection" *.py | grep -v "^generate_collection"
```

Expected: suite OK; импорты `generate_collection` в тестах остались только для `main` (и `default_out_path`, если используется).

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: how-to-add-a-format guide; AGENTS.md with commit and code conventions"
```

---

## Self-Review (выполнен при составлении)

- **Spec coverage:** core-список (Task 1), FormatSpec/BuildContext/FORMATS/lru_cache (Task 5), переносы четырёх форматных модулей (Tasks 2-5), merge за реестром + keep_old_items (Task 6), унифицированный CLI + golden + default_out_path (Task 7), сниффинг-приоритет + pick_format-легаси + `--schema` только opencollection (Task 8), контрактные тесты (Tasks 5, 9), README-гайд + AGENTS.md (Task 10). Ограничение «re-export слой не делаем» — миграции тестов в Tasks 1-6.
- **Placeholder scan:** TBD/TODO нет; механические переносы даны списками имён с grep-проверками (операция, а не заглушка).
- **Type consistency:** `write -> (file_count, note)` единообразно (postman возвращает note, остальные `""`); `build(ctx) -> (payload, stats)` у всех спек; `matches(path) -> bool`; `validate(path, schema_override=None)`; `tree_prune_orphans/v3_prune_orphans(out, collection)`.
