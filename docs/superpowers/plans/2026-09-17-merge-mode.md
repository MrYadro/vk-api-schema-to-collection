# Merge-Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Флаги `--merge` (обновление существующего вывода tree/bundled/postman-v3 без потери пользовательских данных) и `--prune` (удаление запросов/папок, отсутствующих в новой схеме).

**Architecture:** Merge выполняется в пространстве внутренней модели collection-dict: обратные загрузчики (`load_bundled`, `load_tree`, `load_postman_v3`) читают существующий вывод, `merge()` применяет правила защиты слотов, существующие writers пишут результат без изменений. Orphan-чистка `prune_orphans()` удаляет файлы, не вошедшие в модель.

**Tech Stack:** Python 3 stdlib; PyYAML — только ленивый импорт внутри merge_collection (генерация без `--merge` остаётся stdlib-only); тесты — unittest.

**Spec:** `docs/superpowers/specs/2026-09-17-merge-mode-design.md`

## Global Constraints

- Генерация без `--merge`/`--prune` — только stdlib (текущее свойство проекта). PyYAML импортируется лениво внутри `merge_collection` с понятной ошибкой при отсутствии.
- Без комментариев в коде (правило AGENTS.md).
- Тесты: `python3 -m unittest discover -p "test_*.py"` из корня репо, стиль unittest как в `test_generate_collection.py`.
- В фикстурах только синтетические значения (никаких реальных токенов).
- Правило merge из спеки: защищаемый слот — старое значение сохраняется, если отличается от генерируемого; исключение — имя `apiVersion` всегда из генерации.
- Коммиты: английский, императив, развёрнутое сообщение (стиль `git log --oneline`).
- Функции и имена из этого плана — контракт: `merge(new, old, prune=False, keep_old_items=True) -> (dict, dict)`, `load_existing(out_path, fmt) -> dict | None`, `prune_orphans(out_path, fmt, collection) -> list[pathlib.Path]`.

## File Structure

- Create: `merge_collection.py` — загрузчики + merge + orphan-чистка. Не импортирует `generate_collection` (нет цикла).
- Create: `test_merge_collection.py` — все тесты merge-режима.
- Modify: `generate_collection.py` — только `main()`: два аргумента, проверка форматов, вызов load/merge/prune, печать статистики.
- Modify: `README.md` — строки `--merge`/`--prune` в CLI-reference и раздел «Обновление существующей коллекции».

---

### Task 1: `merge()` — переменные (env и коллекционные)

**Files:**
- Create: `merge_collection.py`
- Test: `test_merge_collection.py`

**Interfaces:**
- Produces: `merge(new, old, prune=False, keep_old_items=True) -> (collection, stats)`; stats keys: `added, updated, kept, pruned, preserved_values, preserved_disabled`; приватные `_merge_variables(new_vars, old_vars, stats)`.

- [ ] **Step 1: Write the failing test**

```python
import copy
import unittest

import merge_collection as m


def new_collection():
    return {
        "opencollection": "1.0.0",
        "info": {"name": "VK API", "version": "5.200 (2026-09-17)"},
        "request": {
            "auth": {"type": "bearer", "token": "{{accessToken}}"},
            "variables": [
                {"name": "baseUrl", "value": "https://api.vk.ru"},
                {"name": "apiVersion", "value": "5.200"},
            ],
        },
        "config": {
            "environments": [
                {
                    "name": "api.vk.ru",
                    "variables": [
                        {"name": "baseUrl", "value": "https://api.vk.ru"},
                        {"name": "apiVersion", "value": "5.200"},
                        {"secret": True, "name": "accessToken", "value": ""},
                    ],
                }
            ]
        },
        "items": [],
    }


class TestMergeVariables(unittest.TestCase):
    def setUp(self):
        self.new = new_collection()

    def test_env_user_value_preserved_on_diff(self):
        old = new_collection()
        old["config"]["environments"][0]["variables"][2]["value"] = "tok-123"
        merged, stats = m.merge(self.new, old)
        env = merged["config"]["environments"][0]["variables"]
        self.assertEqual([v for v in env if v["name"] == "accessToken"][0]["value"], "tok-123")
        self.assertEqual(stats["preserved_values"], 1)

    def test_env_equal_value_replaced_silently(self):
        old = new_collection()
        merged, stats = m.merge(self.new, old)
        env = merged["config"]["environments"][0]["variables"]
        self.assertEqual([v for v in env if v["name"] == "baseUrl"][0]["value"], "https://api.vk.ru")
        self.assertEqual(stats["preserved_values"], 0)

    def test_api_version_always_regenerated(self):
        old = new_collection()
        old["config"]["environments"][0]["variables"][1]["value"] = "5.199"
        old["request"]["variables"][1]["value"] = "5.199"
        merged, stats = m.merge(self.new, old)
        env = merged["config"]["environments"][0]["variables"]
        self.assertEqual([v for v in env if v["name"] == "apiVersion"][0]["value"], "5.200")
        self.assertEqual(merged["request"]["variables"][1]["value"], "5.200")
        self.assertEqual(stats["preserved_values"], 0)

    def test_old_only_env_var_appended(self):
        old = new_collection()
        old["config"]["environments"][0]["variables"].append(
            {"name": "myVar", "value": "x", "description": "моё"}
        )
        merged, _ = m.merge(self.new, old)
        env = merged["config"]["environments"][0]["variables"]
        self.assertEqual([v for v in env if v["name"] == "myVar"][0]["value"], "x")

    def test_collection_variables_same_rules(self):
        old = new_collection()
        old["request"]["variables"][0]["value"] = "https://api.vk.com"
        old["request"]["variables"].append({"name": "retries", "value": "3"})
        merged, stats = m.merge(self.new, old)
        self.assertEqual(merged["request"]["variables"][0]["value"], "https://api.vk.com")
        self.assertEqual([v for v in merged["request"]["variables"] if v["name"] == "retries"][0]["value"], "3")
        self.assertEqual(stats["preserved_values"], 1)

    def test_inputs_not_mutated(self):
        old = new_collection()
        old["config"]["environments"][0]["variables"][2]["value"] = "tok-123"
        snapshot_new, snapshot_old = copy.deepcopy(self.new), copy.deepcopy(old)
        m.merge(self.new, old)
        self.assertEqual(self.new, snapshot_new)
        self.assertEqual(old, snapshot_old)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_merge_collection -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'merge_collection'`

- [ ] **Step 3: Write minimal implementation**

`merge_collection.py`:

```python
import copy


def merge(new, old, prune=False, keep_old_items=True):
    merged = copy.deepcopy(new)
    old = copy.deepcopy(old)
    stats = {
        "added": 0,
        "updated": 0,
        "kept": 0,
        "pruned": 0,
        "preserved_values": 0,
        "preserved_disabled": 0,
    }
    _merge_variables(
        (merged.get("request") or {}).get("variables") or [],
        (old.get("request") or {}).get("variables") or [],
        stats,
    )
    old_envs = {(e.get("name") or ""): e for e in (old.get("config") or {}).get("environments") or []}
    for env in (merged.get("config") or {}).get("environments") or []:
        old_env = old_envs.get(env.get("name") or "")
        if old_env is not None:
            _merge_variables(env.get("variables") or [], old_env.get("variables") or [], stats)
    return merged, stats


def _merge_variables(new_vars, old_vars, stats):
    old_by_name = {v.get("name") or "": v for v in old_vars}
    present = set()
    for var in new_vars:
        name = var.get("name") or ""
        present.add(name)
        old_var = old_by_name.get(name)
        if old_var is None or name == "apiVersion":
            continue
        if old_var.get("value", "") != var.get("value", ""):
            var["value"] = old_var.get("value", "")
            stats["preserved_values"] += 1
    for name, old_var in old_by_name.items():
        if name and name not in present:
            new_vars.append(copy.deepcopy(old_var))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_merge_collection -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add merge_collection.py test_merge_collection.py
git commit -m "merge_collection: value-slot rules for env and collection variables (user value wins on diff, apiVersion always regenerated)"
```

---

### Task 2: `merge()` — строки body запросов

**Files:**
- Modify: `merge_collection.py`
- Test: `test_merge_collection.py`

**Interfaces:**
- Consumes: `merge()` из Task 1.
- Produces: приватные `_merge_rows(new_rows, old_rows, stats) -> list`, `_protect_slots(new_row, old_row, stats)`, `_merge_request(req, old_req, stats)`; модель запроса: `http.body.data` — строки `{"name", "value", "disabled"?, "description"?}`.

- [ ] **Step 1: Write the failing test**

Добавить в `test_merge_collection.py`:

```python
def request_with_rows(rows, name="users.get"):
    return {
        "info": {"name": name, "type": "http", "seq": 1},
        "http": {
            "method": "POST",
            "url": "{{baseUrl}}/method/users.get",
            "auth": "inherit",
            "body": {"type": "form-urlencoded", "data": rows},
        },
    }


def folder_with(reqs):
    return {"info": {"name": "Users", "type": "folder", "seq": 2}, "request": {"auth": "inherit"}, "items": reqs}


def collection_with(folder):
    c = new_collection()
    c["items"] = [folder]
    return c


class TestMergeRows(unittest.TestCase):
    def test_user_value_wins_on_diff(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True, "description": "новое"},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "bdate", "disabled": True, "description": "старое"},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        merged, stats = m.merge(new, old)
        data = merged["items"][0]["items"][0]["http"]["body"]["data"]
        self.assertEqual(data[0]["value"], "bdate")
        self.assertEqual(data[0]["description"], "новое")
        self.assertEqual(stats["preserved_values"], 1)

    def test_equal_value_replaced_silently(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
        ])]))
        _, stats = m.merge(new, old)
        self.assertEqual(stats["preserved_values"], 0)
        self.assertEqual(stats["preserved_disabled"], 0)

    def test_user_disabled_state_wins(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": ""},
        ])]))
        merged, stats = m.merge(new, old)
        row = merged["items"][0]["items"][0]["http"]["body"]["data"][0]
        self.assertNotIn("disabled", row)
        self.assertEqual(stats["preserved_disabled"], 1)

    def test_enum_group_matched_by_value(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "sort", "value": "name", "disabled": True},
            {"name": "sort", "value": "date", "disabled": True},
            {"name": "sort", "value": "id", "disabled": True},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "sort", "value": "name", "disabled": True},
            {"name": "sort", "value": "date"},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        merged, _ = m.merge(new, old)
        data = merged["items"][0]["items"][0]["http"]["body"]["data"]
        sorts = [r for r in data if r["name"] == "sort"]
        self.assertEqual([r["value"] for r in sorts], ["name", "date", "id"])
        self.assertEqual([r.get("disabled", False) for r in sorts], [True, False, True])
        self.assertEqual(data[-1]["name"], "v")

    def test_old_only_row_kept_before_v(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
            {"name": "custom", "value": "42", "description": "моё"},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        merged, _ = m.merge(new, old)
        data = merged["items"][0]["items"][0]["http"]["body"]["data"]
        self.assertEqual([r["name"] for r in data], ["fields", "custom", "v"])
        self.assertEqual(data[1]["value"], "42")

    def test_missing_old_body_untouched(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        old = collection_with(folder_with([{"info": {"name": "users.get", "type": "http", "seq": 1}}]))
        merged, stats = m.merge(new, old)
        data = merged["items"][0]["items"][0]["http"]["body"]["data"]
        self.assertEqual(data, [{"name": "v", "value": "{{apiVersion}}"}])
        self.assertEqual(stats["preserved_values"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_merge_collection.TestMergeRows -v`
Expected: FAIL — значения перезаписываются (`assertEqual(data[0]["value"], "bdate")` даёт `''`)

- [ ] **Step 3: Write minimal implementation**

Добавить в `merge_collection.py` и вызвать из `merge()` после переменных (заглушки `_merge_folder` появятся в Task 3; пока в `merge()` после env-цикла):

```python
def _protect_slots(new_row, old_row, stats):
    if old_row.get("value", "") != new_row.get("value", ""):
        new_row["value"] = old_row.get("value", "")
        stats["preserved_values"] += 1
    old_disabled = bool(old_row.get("disabled", False))
    new_disabled = bool(new_row.get("disabled", False))
    if old_disabled != new_disabled:
        if old_disabled:
            new_row["disabled"] = True
        else:
            new_row.pop("disabled", None)
        stats["preserved_disabled"] += 1


def _merge_rows(new_rows, old_rows, stats):
    old_by_name = {}
    for row in old_rows:
        old_by_name.setdefault(row.get("name") or "", []).append(row)
    used = set()
    out = []
    for nr in new_rows:
        group = old_by_name.get(nr.get("name") or "", [])
        available = [r for r in group if id(r) not in used]
        match = None
        if len(group) == 1 and len(available) == 1:
            match = available[0]
        else:
            for r in available:
                if (r.get("value") or "") == (nr.get("value") or ""):
                    match = r
                    break
        if match is not None:
            used.add(id(match))
            _protect_slots(nr, match, stats)
        out.append(nr)
    v_index = len(out)
    for i, nr in enumerate(out):
        if nr.get("name") == "v":
            v_index = i
            break
    out[v_index:v_index] = [r for r in old_rows if id(r) not in used]
    return out


def _merge_request(req, old_req, stats):
    body = (req.get("http") or {}).get("body") or {}
    old_body = (old_req.get("http") or {}).get("body") or {}
    if isinstance(body.get("data"), list) and isinstance(old_body.get("data"), list):
        body["data"] = _merge_rows(body["data"], old_body["data"], stats)
```

В `merge()` после цикла по env — временный проход по items (в Task 3 заменится на `_merge_folder`):

```python
    for folder in merged.get("items") or []:
        for req in folder.get("items") or []:
            _merge_request(req, {"http": {"body": {}}})
```

Внимание: это заглушка только для запуска тестов Task 2 — в Step 3 Task 3 она удаляется. Тесты Task 2 требуют сопоставления запросов по имени, поэтому если тесты не проходят с заглушкой — сразу реализовать сопоставление: заменить заглушку на:

```python
    old_requests = {}
    for folder in old.get("items") or []:
        for r in folder.get("items") or []:
            old_requests[r.get("info", {}).get("name")] = r
    for folder in merged.get("items") or []:
        for req in folder.get("items") or []:
            old_req = old_requests.get(req.get("info", {}).get("name"))
            if old_req is not None:
                _merge_request(req, old_req, stats)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_merge_collection -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add merge_collection.py test_merge_collection.py
git commit -m "merge_collection: body row merge by parameter name (value/disabled user state wins on diff, enum groups matched by value, old-only rows kept before v)"
```

---

### Task 3: `merge()` — items: папки, запросы, пользовательские ключи, пересортировка

**Files:**
- Modify: `merge_collection.py`
- Test: `test_merge_collection.py`

**Interfaces:**
- Consumes: `_merge_request`, `_merge_variables` из Tasks 1-2.
- Produces: приватные `_merge_folder(folder, old_folder, stats, prune, keep_old_items)`, `_norm_name(name)`; финальная семантика `merge()` (готова для интеграции в Task 8).

- [ ] **Step 1: Write the failing test**

Добавить:

```python
class TestMergeItems(unittest.TestCase):
    def test_match_by_name_and_user_keys_preserved(self):
        new = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old["items"][0]["items"][0]["bruno"] = {"scripts": {"post": "x"}}
        old["items"][0]["mynote"] = "заметка"
        merged, stats = m.merge(new, old)
        req = merged["items"][0]["items"][0]
        self.assertEqual(req["bruno"], {"scripts": {"post": "x"}})
        self.assertEqual(merged["items"][0]["mynote"], "заметка")
        self.assertEqual(stats["updated"], 1)

    def test_old_only_request_kept_in_model(self):
        new = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old = collection_with(folder_with([
            request_with_rows([{"name": "v", "value": "{{apiVersion}}"}]),
            request_with_rows([{"name": "q", "value": ""}], name="users.old"),
        ]))
        merged, stats = m.merge(new, old)
        names = [r["info"]["name"] for r in merged["items"][0]["items"]]
        self.assertEqual(names, ["users.get", "users.old"])
        self.assertEqual(stats["kept"], 1)

    def test_old_only_request_not_in_model_when_partial(self):
        new = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old = collection_with(folder_with([
            request_with_rows([{"name": "v", "value": "{{apiVersion}}"}]),
            request_with_rows([{"name": "q", "value": ""}], name="users.old"),
        ]))
        merged, stats = m.merge(new, old, keep_old_items=False)
        names = [r["info"]["name"] for r in merged["items"][0]["items"]]
        self.assertEqual(names, ["users.get"])
        self.assertEqual(stats["kept"], 1)

    def test_prune_drops_old_only(self):
        new = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old = collection_with(folder_with([
            request_with_rows([{"name": "v", "value": "{{apiVersion}}"}]),
            request_with_rows([{"name": "q", "value": ""}], name="users.old"),
        ]))
        old_folder = folder_with([request_with_rows([{"name": "q", "value": ""}], name="ghost.method")])
        old_folder["info"]["name"] = "Ghost"
        old["items"].append(old_folder)
        merged, stats = m.merge(new, old, prune=True)
        names = [r["info"]["name"] for r in merged["items"][0]["items"]]
        folder_names = [f["info"]["name"] for f in merged["items"]]
        self.assertEqual(names, ["users.get"])
        self.assertEqual(folder_names, ["Users"])
        self.assertEqual(stats["pruned"], 3)

    def test_meta_folder_head_not_duplicated(self):
        new = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        meta = {"info": {"name": "_Meta", "type": "folder", "seq": 1}, "items": [
            {"info": {"name": "Проверка токена (users.get)", "type": "http", "seq": 1},
             "http": {"body": {"type": "form-urlencoded", "data": [
                 {"name": "fields", "value": "bdate", "disabled": True},
                 {"name": "v", "value": "{{apiVersion}}"},
             ]}}},
        ]}
        new["items"] = [meta, new["items"][0]]
        old_meta = copy.deepcopy(meta)
        old_meta["items"][0]["http"]["body"]["data"][0]["disabled"] = False
        old = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old["items"] = [old_meta, old["items"][0]]
        merged, stats = m.merge(new, old)
        folder_names = [f["info"]["name"] for f in merged["items"]]
        self.assertEqual(folder_names, ["_Meta", "Users"])
        row = merged["items"][0]["items"][0]["http"]["body"]["data"][0]
        self.assertNotIn("disabled", row)
        self.assertEqual(stats["kept"], 0)

    def test_resort_and_seq_renumber(self):
        meta = {"info": {"name": "_Meta", "type": "folder"}, "items": []}
        users = folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])])
        wall = {"info": {"name": "Wall", "type": "folder"}, "items": []}
        apps = {"info": {"name": "Apps", "type": "folder"}, "items": []}
        new = collection_with(users)
        new["items"] = [meta, users, wall]
        old = collection_with(users)
        old["items"] = [copy.deepcopy(users), copy.deepcopy(apps)]
        merged, stats = m.merge(new, old)
        self.assertEqual([f["info"]["name"] for f in merged["items"]], ["_Meta", "Apps", "Users", "Wall"])
        self.assertEqual([f["info"]["seq"] for f in merged["items"]], [1, 2, 3, 4])
        self.assertEqual(merged["items"][2]["items"][0]["info"]["seq"], 1)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["added"], 1)

    def test_collection_level_user_keys_preserved(self):
        new = new_collection()
        old = new_collection()
        old["customtop"] = {"x": 1}
        merged, _ = m.merge(new, old)
        self.assertEqual(merged["customtop"], {"x": 1})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_merge_collection.TestMergeItems -v`
Expected: FAIL — нет `_merge_folder`, нет пересортировки/renumber, `_Meta` дублируется как old-only

- [ ] **Step 3: Write minimal implementation**

Добавить в `merge_collection.py` (вверху файла):

```python
import re

V3_UNSAFE = re.compile(r"[/\\:]")


def _norm_name(name):
    return V3_UNSAFE.sub("_", name or "")
```

Добавить:

```python
def _merge_folder(folder, old_folder, stats, prune, keep_old_items):
    old_requests = {}
    for r in old_folder.get("items") or []:
        old_requests[_norm_name((r.get("info") or {}).get("name"))] = r
    out = []
    for req in folder.get("items") or []:
        old_req = old_requests.pop(_norm_name((req.get("info") or {}).get("name")), None)
        if old_req is None:
            stats["added"] += 1
        else:
            stats["updated"] += 1
            _merge_request(req, old_req, stats)
            for k, v in old_req.items():
                if k not in req:
                    req[k] = copy.deepcopy(v)
        out.append(req)
    for old_req in old_requests.values():
        if prune:
            stats["pruned"] += 1
        else:
            stats["kept"] += 1
            if keep_old_items:
                out.append(old_req)
    folder["items"] = out
    for k, v in old_folder.items():
        if k != "items" and k not in folder:
            folder[k] = copy.deepcopy(v)
```

Переписать хвостовую часть `merge()` (заменить временную заглушку из Task 2 — весь проход по items):

```python
    old_folders = {}
    for f in old.get("items") or []:
        old_folders[_norm_name((f.get("info") or {}).get("name"))] = f
    items = merged.get("items") or []
    if items:
        old_head = old_folders.pop(_norm_name((items[0].get("info") or {}).get("name")), None)
        if old_head is not None:
            _merge_folder(items[0], old_head, stats, prune, keep_old_items)
    rest = items[1:]
    for folder in rest:
        old_folder = old_folders.pop(_norm_name((folder.get("info") or {}).get("name")), None)
        if old_folder is None:
            stats["added"] += 1 + len(folder.get("items") or [])
        else:
            _merge_folder(folder, old_folder, stats, prune, keep_old_items)
    for old_folder in old_folders.values():
        count = 1 + len(old_folder.get("items") or [])
        if prune:
            stats["pruned"] += count
        else:
            stats["kept"] += count
            if keep_old_items:
                rest.append(old_folder)
    rest.sort(key=lambda f: (f.get("info") or {}).get("name") or "")
    items = ([items[0]] if items else []) + rest
    merged["items"] = items
    for i, folder in enumerate(items):
        folder.setdefault("info", {})["seq"] = i + 1
        for j, req in enumerate(folder.get("items") or []):
            req.setdefault("info", {})["seq"] = j + 1
    for k, v in old.items():
        if k not in merged:
            merged[k] = copy.deepcopy(v)
    return merged, stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_merge_collection -v`
Expected: PASS (19 tests)

- [ ] **Step 5: Commit**

```bash
git add merge_collection.py test_merge_collection.py
git commit -m "merge_collection: folder/request merge by name, user keys preserved, old-only items kept or pruned, alphabetical resort with seq renumber, _Meta head merged not duplicated"
```

---

### Task 4: Загрузчик bundled + ленивый PyYAML

**Files:**
- Modify: `merge_collection.py`
- Test: `test_merge_collection.py`

**Interfaces:**
- Produces: `load_bundled(path) -> dict | None`, `_require_yaml()` (SystemExit с сообщением при отсутствии PyYAML).

- [ ] **Step 1: Write the failing test**

Добавить:

```python
class TestLoadBundled(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")
        import generate_collection as g
        self.g = g

    def test_round_trip(self):
        doc = {**new_collection(), "bundled": True}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.yaml"
            path.write_text(self.g.to_yaml(doc), encoding="utf-8")
            loaded = m.load_bundled(path)
            self.assertEqual(loaded, new_collection())

    def test_missing_file_returns_none(self):
        self.assertIsNone(m.load_bundled(pathlib.Path("/nonexistent/c.yaml")))
```

Обновить импорты вверху `test_merge_collection.py`:

```python
import copy
import pathlib
import tempfile
import unittest

import merge_collection as m
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_merge_collection.TestLoadBundled -v`
Expected: FAIL — `AttributeError: module 'merge_collection' has no attribute 'load_bundled'`

- [ ] **Step 3: Write minimal implementation**

Добавить в `merge_collection.py` (вверху добавить `import pathlib`):

```python
def _require_yaml():
    try:
        import yaml
    except ImportError:
        raise SystemExit("--merge/--prune need PyYAML: pip install pyyaml")
    return yaml


def load_bundled(path):
    path = pathlib.Path(path)
    if not path.is_file():
        return None
    doc = _require_yaml().safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return None
    doc.pop("bundled", None)
    return doc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_merge_collection -v`
Expected: PASS (21 tests)

- [ ] **Step 5: Commit**

```bash
git add merge_collection.py test_merge_collection.py
git commit -m "merge_collection: bundled loader with lazy PyYAML import and clear missing-dependency error"
```

---

### Task 5: Загрузчик tree

**Files:**
- Modify: `merge_collection.py`
- Test: `test_merge_collection.py`

**Interfaces:**
- Consumes: `_require_yaml()` из Task 4; `generate_collection.write_tree` (только в тесте).
- Produces: `load_tree(out_dir) -> dict | None` — полная модель: root + config.environments + items (сортировка по `info.seq`).

- [ ] **Step 1: Write the failing test**

Добавить (фикстура — `COLLECTION` из `test_generate_collection.py`, расширенная папкой):

```python
from test_generate_collection import COLLECTION as BASE_COLLECTION

TREE_COLLECTION = copy.deepcopy(BASE_COLLECTION)
TREE_COLLECTION["items"][0]["items"].append(
    {
        "info": {"name": "users.search", "type": "http", "seq": 2, "description": "Поиск пользователей."},
        "http": {
            "method": "POST",
            "url": "{{baseUrl}}/method/users.search",
            "auth": "inherit",
            "body": {"type": "form-urlencoded", "data": [{"name": "q", "value": "", "disabled": True}, {"name": "v", "value": "{{apiVersion}}"}]},
        },
        "docs": "# users.search",
    }
)


class TestLoadTree(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")
        import generate_collection as g
        self.g = g

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api"
            self.g.write_tree(TREE_COLLECTION, out)
            loaded = m.load_tree(out)
            self.assertEqual(loaded["info"], TREE_COLLECTION["info"])
            self.assertEqual(loaded["request"], TREE_COLLECTION["request"])
            folder = loaded["items"][0]
            self.assertEqual(folder["info"]["name"], "Users")
            self.assertEqual([r["info"]["name"] for r in folder["items"]], ["users.get", "users.search"])
            self.assertEqual(
                folder["items"][0]["http"]["body"]["data"],
                TREE_COLLECTION["items"][0]["items"][0]["http"]["body"]["data"],
            )
            envs = loaded["config"]["environments"]
            self.assertEqual(len(envs), 1)
            self.assertEqual([v["name"] for v in envs[0]["variables"]], ["baseUrl", "apiVersion", "accessToken", "groupToken"])

    def test_missing_dir_returns_none(self):
        self.assertIsNone(m.load_tree(pathlib.Path("/nonexistent/vk-api")))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_merge_collection.TestLoadTree -v`
Expected: FAIL — `AttributeError: ... no attribute 'load_tree'`

- [ ] **Step 3: Write minimal implementation**

Добавить в `merge_collection.py`:

```python
def load_tree(out_dir):
    out_dir = pathlib.Path(out_dir)
    root_file = out_dir / "opencollection.yml"
    if not root_file.is_file():
        return None
    yaml = _require_yaml()
    collection = yaml.safe_load(root_file.read_text(encoding="utf-8"))
    if not isinstance(collection, dict):
        return None
    env_dir = out_dir / "environments"
    envs = []
    if env_dir.is_dir():
        for f in sorted(env_dir.glob("*.yml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                envs.append(doc)
    collection["config"] = {"environments": envs}
    folders = []
    for d in sorted(p for p in out_dir.iterdir() if p.is_dir() and p.name != "environments"):
        folder_doc = {"info": {"name": d.name, "type": "folder"}}
        folder_file = d / "folder.yml"
        if folder_file.is_file():
            doc = yaml.safe_load(folder_file.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                folder_doc = doc
        requests = []
        for f in sorted(d.glob("*.yml")):
            if f.name == "folder.yml":
                continue
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and isinstance(doc.get("info"), dict):
                requests.append(doc)
        requests.sort(key=lambda r: r["info"].get("seq") or 0)
        folder_doc["items"] = requests
        folders.append(folder_doc)
    folders.sort(key=lambda f: (f.get("info") or {}).get("seq") or 0)
    collection["items"] = folders
    return collection
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_merge_collection -v`
Expected: PASS (23 tests)

- [ ] **Step 5: Commit**

```bash
git add merge_collection.py test_merge_collection.py
git commit -m "merge_collection: tree loader reconstructing full model from opencollection.yml, environments and per-folder request files ordered by seq"
```

---

### Task 6: Загрузчик postman-v3 + диспетчер `load_existing`

**Files:**
- Modify: `merge_collection.py`
- Test: `test_merge_collection.py`

**Interfaces:**
- Consumes: `_require_yaml()`; `generate_collection.write_postman_v3` (в тесте).
- Produces: `load_postman_v3(out_dir) -> dict | None` — частичная модель (body rows, env values, definition variables); `load_existing(out_path, fmt) -> dict | None`.

- [ ] **Step 1: Write the failing test**

Добавить:

```python
class TestLoadPostmanV3(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")
        import generate_collection as g
        self.g = g

    def test_partial_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            self.g.write_postman_v3(TREE_COLLECTION, out)
            loaded = m.load_postman_v3(out)
            folder = loaded["items"][0]
            self.assertEqual(folder["info"]["name"], "Users")
            self.assertEqual([r["info"]["name"] for r in folder["items"]], ["users.get", "users.search"])
            self.assertEqual(
                folder["items"][0]["http"]["body"]["data"],
                TREE_COLLECTION["items"][0]["items"][0]["http"]["body"]["data"],
            )
            env = loaded["config"]["environments"][0]
            self.assertEqual(env["name"], "api.vk.ru")
            self.assertEqual([v["name"] for v in env["variables"]], ["baseUrl", "apiVersion", "accessToken", "groupToken"])
            var_values = {v["name"]: v["value"] for v in loaded["request"]["variables"]}
            self.assertEqual(var_values["baseUrl"], "https://api.vk.ru")

    def test_missing_dir_returns_none(self):
        self.assertIsNone(m.load_postman_v3(pathlib.Path("/nonexistent/vk-api-local")))


class TestLoadExistingDispatch(unittest.TestCase):
    def test_dispatch(self):
        self.assertIsNone(m.load_existing(pathlib.Path("/nonexistent"), "openapi"))
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.yaml"
            path.write_text("info:\n  name: x\n", encoding="utf-8")
            self.assertIsNotNone(m.load_existing(path, "bundled"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_merge_collection.TestLoadPostmanV3 test_merge_collection.TestLoadExistingDispatch -v`
Expected: FAIL — `AttributeError: ... no attribute 'load_postman_v3'`

- [ ] **Step 3: Write minimal implementation**

Добавить в `merge_collection.py`:

```python
def load_postman_v3(out_dir):
    out_dir = pathlib.Path(out_dir)
    root = out_dir / "postman"
    if not root.is_dir():
        return None
    yaml = _require_yaml()
    items = []
    variables = []
    envs = []
    collections_dir = root / "collections"
    if collections_dir.is_dir():
        for coll_dir in sorted(collections_dir.iterdir()):
            if not coll_dir.is_dir():
                continue
            def_file = coll_dir / ".resources" / "definition.yaml"
            if def_file.is_file():
                doc = yaml.safe_load(def_file.read_text(encoding="utf-8")) or {}
                for name, value in (doc.get("variables") or {}).items():
                    variables.append({"name": name, "value": value})
            for d in sorted(coll_dir.iterdir()):
                if not d.is_dir() or d.name == ".resources":
                    continue
                requests = []
                for f in sorted(d.glob("*.request.yaml")):
                    doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                    rows = []
                    for row in ((doc.get("body") or {}).get("content") or []):
                        if not isinstance(row, dict):
                            continue
                        out_row = {"name": row.get("key") or "", "value": row.get("value") or ""}
                        if "disabled" in row:
                            out_row["disabled"] = row["disabled"]
                        if row.get("description"):
                            out_row["description"] = row["description"]
                        rows.append(out_row)
                    requests.append(
                        {
                            "info": {"name": f.name[: -len(".request.yaml")], "type": "http"},
                            "http": {"body": {"type": "form-urlencoded", "data": rows}},
                        }
                    )
                if requests:
                    items.append({"info": {"name": d.name, "type": "folder"}, "items": requests})
    env_dir = root / "environments"
    if env_dir.is_dir():
        for f in sorted(env_dir.glob("*.environment.yaml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            envs.append(
                {
                    "name": doc.get("name") or f.name[: -len(".environment.yaml")],
                    "variables": [
                        {"name": v.get("key") or "", "value": v.get("value") or ""}
                        for v in doc.get("values") or []
                        if isinstance(v, dict)
                    ],
                }
            )
    return {
        "info": {"name": "VK API"},
        "request": {"variables": variables},
        "config": {"environments": envs},
        "items": items,
    }


def load_existing(out_path, fmt):
    if fmt == "bundled":
        return load_bundled(out_path)
    if fmt == "tree":
        return load_tree(out_path)
    if fmt == "postman-v3":
        return load_postman_v3(out_path)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_merge_collection -v`
Expected: PASS (26 tests)

- [ ] **Step 5: Commit**

```bash
git add merge_collection.py test_merge_collection.py
git commit -m "merge_collection: partial postman-v3 loader (urlencoded rows by request file, environment values, definition variables) and load_existing dispatcher"
```

---

### Task 7: `prune_orphans` — удаление файлов-сирот

**Files:**
- Modify: `merge_collection.py`
- Test: `test_merge_collection.py`

**Interfaces:**
- Consumes: `_norm_name`, `_require_yaml` из Tasks 3-4.
- Produces: `prune_orphans(out_path, fmt, collection) -> list[pathlib.Path]` — удалённые пути; для `bundled` возвращает `[]`.

- [ ] **Step 1: Write the failing test**

Добавить:

```python
def write_stray_tree_request(folder_dir, name):
    doc = {
        "info": {"name": name, "type": "http", "seq": 99},
        "http": {"method": "POST", "url": "{{baseUrl}}/method/" + name, "body": {"type": "form-urlencoded", "data": [{"name": "v", "value": "{{apiVersion}}"}]}},
    }
    import generate_collection as g
    (folder_dir / (name.replace(".", "_") + ".yml")).write_text(g.to_yaml(doc), encoding="utf-8")


class TestPruneOrphans(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")
        import generate_collection as g
        self.g = g

    def test_tree_removes_stray_request_and_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api"
            self.g.write_tree(TREE_COLLECTION, out)
            users_dir = out / "Users"
            write_stray_tree_request(users_dir, "users.old")
            ghost = out / "Ghost"
            ghost.mkdir()
            (ghost / "folder.yml").write_text(self.g.to_yaml({"info": {"name": "Ghost", "type": "folder", "seq": 50}}), encoding="utf-8")
            removed = m.prune_orphans(out, "tree", TREE_COLLECTION)
            removed_names = sorted(p.name for p in removed)
            self.assertIn("users_old.yml", removed_names)
            self.assertIn("Ghost", removed_names)
            self.assertFalse((users_dir / "users.old.yml").exists())
            self.assertFalse(ghost.exists())
            self.assertTrue((users_dir / "folder.yml").exists())

    def test_postman_v3_removes_stray_request_and_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            self.g.write_postman_v3(TREE_COLLECTION, out)
            users_dir = out / "postman" / "collections" / "VK API" / "Users"
            stray = users_dir / "users.old.request.yaml"
            stray.write_text(self.g.to_yaml({"$kind": "http-request", "url": "x", "method": "POST", "body": {"type": "urlencoded", "content": []}}), encoding="utf-8")
            ghost = out / "postman" / "collections" / "VK API" / "Ghost"
            ghost.mkdir()
            removed = m.prune_orphans(out, "postman-v3", TREE_COLLECTION)
            self.assertFalse(stray.exists())
            self.assertFalse(ghost.exists())
            self.assertEqual(len(removed), 2)
            self.assertTrue((users_dir / "users.get.request.yaml").exists())

    def test_bundled_noop(self):
        self.assertEqual(m.prune_orphans(pathlib.Path("/nonexistent/c.yaml"), "bundled", {}), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_merge_collection.TestPruneOrphans -v`
Expected: FAIL — `AttributeError: ... no attribute 'prune_orphans'`

- [ ] **Step 3: Write minimal implementation**

Добавить в `merge_collection.py` (вверху добавить `import shutil`):

```python
def _keep_index(collection):
    keep = {}
    for folder in collection.get("items") or []:
        key = _norm_name((folder.get("info") or {}).get("name"))
        keep[key] = {_norm_name((r.get("info") or {}).get("name")) for r in folder.get("items") or []}
    return keep


def prune_orphans(out_path, fmt, collection):
    out_path = pathlib.Path(out_path)
    removed = []
    keep = _keep_index(collection)
    if fmt == "tree":
        if not out_path.is_dir():
            return removed
        yaml = _require_yaml()
        for d in sorted(p for p in out_path.iterdir() if p.is_dir() and p.name != "environments"):
            folder_name = _norm_name(d.name)
            folder_file = d / "folder.yml"
            if folder_file.is_file():
                doc = yaml.safe_load(folder_file.read_text(encoding="utf-8")) or {}
                folder_name = _norm_name((doc.get("info") or {}).get("name") or d.name)
            keep_requests = keep.get(folder_name)
            if keep_requests is None:
                shutil.rmtree(d)
                removed.append(d)
                continue
            for f in sorted(d.glob("*.yml")):
                if f.name == "folder.yml":
                    continue
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                req_name = _norm_name((doc.get("info") or {}).get("name") or f.stem)
                if req_name not in keep_requests:
                    f.unlink()
                    removed.append(f)
    elif fmt == "postman-v3":
        collections_dir = out_path / "postman" / "collections"
        if not collections_dir.is_dir():
            return removed
        for coll_dir in sorted(collections_dir.iterdir()):
            if not coll_dir.is_dir():
                continue
            for d in sorted(coll_dir.iterdir()):
                if not d.is_dir() or d.name == ".resources":
                    continue
                keep_requests = keep.get(_norm_name(d.name))
                if keep_requests is None:
                    shutil.rmtree(d)
                    removed.append(d)
                    continue
                for f in sorted(d.glob("*.request.yaml")):
                    if _norm_name(f.name[: -len(".request.yaml")]) not in keep_requests:
                        f.unlink()
                        removed.append(f)
    return removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_merge_collection -v`
Expected: PASS (29 tests)

- [ ] **Step 5: Commit**

```bash
git add merge_collection.py test_merge_collection.py
git commit -m "merge_collection: prune_orphans deletes request files and whole folders absent from the model (tree by folder.yml info.name, postman-v3 by request file stems)"
```

---

### Task 8: Интеграция в `main()` — флаги `--merge`/`--prune`

**Files:**
- Modify: `generate_collection.py` (только `main()`, строки ~1030-1097)
- Test: `test_merge_collection.py`

**Interfaces:**
- Consumes: `load_existing`, `merge`, `prune_orphans` из Tasks 4-7.
- Produces: CLI `--merge`, `--prune`; печать `added=… updated=… kept=… pruned=… preserved_values=… preserved_disabled=… [pruned_files=N]`.

- [ ] **Step 1: Write the failing test**

Добавить:

```python
MINI_METHODS = {
    "methods": [
        {
            "name": "users.get",
            "description": "Returns user info",
            "parameters": [{"name": "user_ids", "description": "IDs", "required": True}],
        },
        {
            "name": "users.old",
            "description": "Old method",
            "parameters": [],
        },
    ]
}


MINI_METHODS_V2 = {"methods": [MINI_METHODS["methods"][0]]}


def write_mini_schema(root, methods=MINI_METHODS):
    d = root / "users"
    d.mkdir(parents=True)
    (d / "methods.json").write_text(json.dumps(methods, ensure_ascii=False), encoding="utf-8")
    return root


def run_main(argv):
    import generate_collection as g
    from unittest import mock
    with mock.patch.object(sys, "argv", argv):
        g.main()


class TestMainFlags(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def test_unsupported_format_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema = write_mini_schema(pathlib.Path(tmp) / "schema")
            with self.assertRaises(SystemExit):
                run_main(["generate_collection.py", "--schema-dir", str(schema), "--format", "postman", "--merge"])
            with self.assertRaises(SystemExit):
                run_main(["generate_collection.py", "--schema-dir", str(schema), "--format", "openapi", "--prune"])

    def test_merge_preserves_user_edits_in_tree(self):
        import generate_collection as g
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.199"])
            req_file = out / "Users" / "users.get.yml"
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            doc["http"]["body"]["data"][0]["value"] = "1,2"
            req_file.write_text(g.to_yaml(doc), encoding="utf-8")
            env_file = out / "environments" / "api.vk.ru.yml"
            env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
            [v for v in env["variables"] if v["name"] == "accessToken"][0]["value"] = "tok"
            env_file.write_text(g.to_yaml(env), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            self.assertEqual(doc["http"]["body"]["data"][0]["value"], "1,2")
            v_row = [r for r in doc["http"]["body"]["data"] if r["name"] == "v"][0]
            self.assertEqual(v_row["value"], "{{apiVersion}}")
            env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
            self.assertEqual([v for v in env["variables"] if v["name"] == "accessToken"][0]["value"], "tok")
            self.assertEqual([v for v in env["variables"] if v["name"] == "apiVersion"][0]["value"], "5.200")

    def test_prune_without_merge_removes_stray_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.199"])
            old_file = out / "Users" / "users.removed.yml"
            old_file.write_text("info:\n  name: users.removed\n  type: http\n  seq: 99\n", encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.199", "--prune"])
            self.assertFalse(old_file.exists())
            self.assertTrue((out / "Users" / "users.get.yml").exists())
```

Обновить импорты вверху теста: добавить `import json`, `import sys` и после пропуска pyyaml — `import yaml` локально в тестах, где используется (в `TestMainFlags` уже есть паттерн `try: import yaml`).

Примечание: `run_main` вызывает `g.main()`, который печатает статистику — это нормально для теста.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_merge_collection.TestMainFlags -v`
Expected: FAIL — `SystemExit: 2` от argparse (unrecognized arguments: --merge)

- [ ] **Step 3: Write minimal implementation**

В `generate_collection.py`, `main()`:

После строки с `--dump-json` (строка ~1039) добавить:

```python
    parser.add_argument("--merge", action="store_true", help="update existing output instead of replacing (tree, bundled, postman-v3)")
    parser.add_argument("--prune", action="store_true", help="delete requests and folders absent from the new schema (tree, bundled, postman-v3)")
```

После блока `if args.out is None: args.out = default_out_path(args.format)` добавить:

```python
    if (args.merge or args.prune) and args.format not in ("tree", "bundled", "postman-v3"):
        parser.error("--merge/--prune are only supported for tree, bundled and postman-v3")
```

После строки `collection, stats = build(...)` добавить:

```python
    merge_stats = None
    if args.merge:
        import merge_collection
        old = merge_collection.load_existing(args.out, args.format)
        if old is not None:
            collection, merge_stats = merge_collection.merge(
                collection, old, prune=args.prune, keep_old_items=args.format != "postman-v3"
            )
```

Перед финальным `print(` (после блока `--dump-json`) добавить:

```python
    pruned_files = []
    if args.prune:
        import merge_collection
        pruned_files = merge_collection.prune_orphans(args.out, args.format, collection)
    extra = ""
    if merge_stats is not None:
        extra += " " + " ".join(f"{k}={v}" for k, v in merge_stats.items())
    if pruned_files:
        extra += f" pruned_files={len(pruned_files)}"
```

И в финальном `print(...)` последним аргументом после `(f" ({size})")` добавить `+ extra`:

```python
    print(
        f"format={args.format} folders={stats['folders']} requests={stats['requests']} "
        f"files={file_count} collisions={stats['collisions']} encodings={','.join(stats['encodings'])} "
        f"ru_descriptions={stats['ru_descriptions']} out={args.out}"
        + (f" +{len(env_paths)} environment file(s)" if env_paths else "")
        + f" ({size})"
        + extra
    )
```

Внимание: блок `--prune` должен стоять до финального print, но после записи вывода всеми writer-ветками (tree/bundled/postman-v3). Для формата `openapi` функция возвращается раньше — merge/prune для него уже запрещены `parser.error`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_merge_collection -v`
Expected: PASS (32 tests)

- [ ] **Step 5: Run full suite (регресс)**

Run: `python3 -m unittest discover -p "test_*.py" -v`
Expected: PASS — все существующие тесты + новые

- [ ] **Step 6: Commit**

```bash
git add generate_collection.py test_merge_collection.py
git commit -m "generate_collection: --merge/--prune flags wired into main (load existing output, merge model, prune orphan files, print merge stats)"
```

---

### Task 9: End-to-end merge для bundled и postman-v3 + валидация

**Files:**
- Test: `test_merge_collection.py`

**Interfaces:**
- Consumes: всё из Tasks 1-8; `validate_collection.validate_postman_v3(out)` (структурная проверка, offline).

- [ ] **Step 1: Write the failing test**

Добавить:

```python
class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")
        import generate_collection as g
        self.g = g

    def test_bundled_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            out = root / "vk-api.yaml"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "bundled", "--api-version", "5.199"])
            doc = yaml.safe_load(out.read_text(encoding="utf-8"))
            doc["config"]["environments"][0]["variables"][2]["value"] = "tok-b"
            out.write_text(self.g.to_yaml(doc), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "bundled", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(out.read_text(encoding="utf-8"))
            env = doc["config"]["environments"][0]["variables"]
            self.assertEqual([v for v in env if v["name"] == "accessToken"][0]["value"], "tok-b")
            self.assertEqual([v for v in env if v["name"] == "apiVersion"][0]["value"], "5.200")
            self.assertIn("bundled", doc)

    def test_postman_v3_merge_and_prune(self):
        import validate_collection as v
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            schema_v2 = write_mini_schema(root / "schema2", MINI_METHODS_V2)
            out = root / "vk-api-local"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "postman-v3", "--api-version", "5.199"])
            req_file = out / "postman" / "collections" / "VK API" / "Users" / "users.get.request.yaml"
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            doc["body"]["content"][0]["value"] = "1,2"
            req_file.write_text(self.g.to_yaml(doc), encoding="utf-8")
            env_file = out / "postman" / "environments" / "api.vk.ru.environment.yaml"
            env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
            [x for x in env["values"] if x["key"] == "accessToken"][0]["value"] = "tok-v3"
            env_file.write_text(self.g.to_yaml(env), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema_v2), "--out", str(out), "--format", "postman-v3", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            rows = {r["key"]: r for r in doc["body"]["content"] if isinstance(r, dict)}
            self.assertEqual(rows["user_ids"]["value"], "1,2")
            env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
            self.assertEqual([x for x in env["values"] if x["key"] == "accessToken"][0]["value"], "tok-v3")
            self.assertEqual([x for x in env["values"] if x["key"] == "apiVersion"][0]["value"], "5.200")
            old_file = out / "postman" / "collections" / "VK API" / "Users" / "users.old.request.yaml"
            self.assertTrue(old_file.exists())
            folders, requests = v.validate_postman_v3(out)
            self.assertEqual((folders, requests), (1, 2))
            run_main(["generate_collection.py", "--schema-dir", str(schema_v2), "--out", str(out), "--format", "postman-v3", "--api-version", "5.200", "--merge", "--prune"])
            self.assertFalse(old_file.exists())
            folders, requests = v.validate_postman_v3(out)
            self.assertEqual((folders, requests), (1, 1))
```

Примечание: первая генерация идёт по полной mini-schema (users.get + users.old), merge-прогоны — по сокращённой MINI_METHODS_V2 (только users.get): users.old становится old-only (в модели нет, файл на диске остаётся), prune-прогон его удаляет. `validate_postman_v3` считает (folders, requests) по файлам на диске.

- [ ] **Step 2: Run test to verify it fails or passes honestly**

Run: `python3 -m unittest test_merge_collection.TestEndToEnd -v`
Expected: FAIL до Task 8 недоступен (если Tasks 1-8 выполнены — возможно сразу PASS; тогда это подтверждающий тест, зафиксировать как регрессионный)

- [ ] **Step 3: Fix if needed**

Если ассерты не сходятся — отладить по месту (типовые проблемы: `env["values"]` вместо `variables` в v3 env yaml — ключ `key`, не `name`; пути коллекций содержат имя `VK API` с пробелом).

- [ ] **Step 4: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add test_merge_collection.py
git commit -m "merge_collection tests: end-to-end merge for bundled and postman-v3 (token preserved, apiVersion refreshed, old-only request kept then pruned, structural v3 validation)"
```

---

### Task 10: README — `--merge`/`--prune` и раздел «Обновление существующей коллекции»

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: CLI из Task 8.

- [ ] **Step 1: Add rows to CLI reference**

В таблицу `### generate_collection.py` (после строки `--dump-json`) добавить:

```markdown
| `--merge` | выкл | Обновить существующий вывод вместо замены (tree, bundled, postman-v3): значения параметров и токены пользователя сохраняются, новые методы добавляются, описания актуализируются, сортировка пересчитывается. |
| `--prune` | выкл | Удалить запросы и папки, отсутствующие в новой схеме (в т.ч. свои запросы в сгенерированных папках). Работает и без `--merge` — как чистка устаревших файлов. |
```

- [ ] **Step 2: Add usage section**

После раздела «Использование» добавить:

```markdown
## Обновление существующей коллекции

Регулярная генерация полностью перезаписывает вывод. Чтобы вести коллекцию руками
(заполненные значения параметров, токены в окружении) и актуализировать её из схемы:

```sh
python3 generate_collection.py --format tree --merge       # обновить, сохранив правки
python3 generate_collection.py --format postman-v3 --merge # то же для Postman Local View
python3 generate_collection.py --format tree --prune       # полная перегенерация + удалить устаревшие файлы
```

Правила: значение параметра/переменной сохраняется, если оно отличается от
генерируемого (пустые генерируемые значения не защищаются); `apiVersion` всегда
из свежей схемы; методы, пропавшие из схемы, остаются (удаляются только с `--prune`;
свои запросы в сгенерированных папках `--prune` тоже удалит). Требует PyYAML
(`pip install pyyaml`).
```

- [ ] **Step 3: Verify docs build nothing to run — check rendering manually**

Run: `python3 generate_collection.py --help | head -5`
Expected: справка выводится; в README нет противоречий (сверить флаги с `--help`).

- [ ] **Step 4: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "README: document --merge/--prune and add 'updating an existing collection' section"
```

---

## Self-Review (выполнен при составлении)

- **Spec coverage:** защищаемые слоты и правило differs→user (Tasks 1-2), apiVersion-исключение (Task 1), пользовательские ключи/строки/old-only (Tasks 2-3), пересортировка+seq (Task 3), загрузчики трёх форматов (Tasks 4-6), orphan-чистка и независимость prune от merge (Tasks 7-8), статистика (Task 8), интеграционные тесты с валидацией (Task 9), README (Task 10). Проверка форматов `postman|openapi` → ошибка (Task 8).
- **Placeholder scan:** TBD/TODO отсутствуют; все шаги содержат код.
- **Type consistency:** `merge(new, old, prune, keep_old_items)`, `load_existing(out_path, fmt)`, `prune_orphans(out_path, fmt, collection)` используются одинаково в Tasks 8-9; `_norm_name`/`_require_yaml` определены до первого использования.
