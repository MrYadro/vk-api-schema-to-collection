# New Export Formats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Четыре новых формата экспорта (`hoppscotch`, `insomnia`, `yaak`, `insomnia-v5`) через реестр `formats/` + таблица сравнения клиентов в README.

**Architecture:** Каждый формат — модуль в `formats/` со спекой (генерация + валидация; yaak/insomnia-v5 — плюс merge: `load_existing`/`prune_orphans`), единый CLI уже не требует правок (реестр). Порядок: сначала простые импорт-форматы (hoppscotch, insomnia v4), затем yaak с merge, затем insomnia-v5 (research-freeze layout → генерация → merge), в конце README.

**Tech Stack:** Python 3 stdlib; ленивый yaml в валидаторах/лоадерах; json для hoppscotch/insomnia.

**Spec:** `docs/superpowers/specs/2026-09-17-new-formats-design.md`

## Global Constraints

- Реестр-контракт неизменен: `FormatSpec` не расширяется; новый формат = модуль + строка в `FORMATS`.
- Все новые спеки: `model_based=True`, `stats_keys=("folders", "requests")`; `supports_merge=True` только у `yaak` и `insomnia-v5`.
- Внешний CLI-контракт стабилен: единый print; для новых форматов — golden full-line regex `^format=<name> folders=\d+ requests=\d+ files=\d+ collisions=\d+ encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+( \+\d+ environment file\(s\))?( \(\d+\.\d MB\))$`-вида (по образцу `TestCliPrintGolden`).
- Контрактные тесты реестра обновляются в каждой задаче (`test_five_formats_registered` → растущий список).
- `validate_collection`: каждое имя добавляется в `SNIFF_PRIORITY` и получает свою OK-ветку печати в `main()` (по образцу существующих).
- Без комментариев в коде; коммиты conventional (`feat:`, `test:`, `docs:`).
- Тестовый раннер: `python3 -m unittest discover -p "test_*.py"` из корня; базовый счёт — 95.
- CI-workflow (release-упаковка) НЕ трогается — артефакты новых форматов в релизе отдельным решением после ревью.

---

### Task 1: `formats/hoppscotch.py` — collection + env JSON

**Files:**
- Create: `formats/hoppscotch.py`
- Modify: `formats/__init__.py` (FORMATS += hoppscotch), `validate_collection.py` (SNIFF_PRIORITY + OK-ветка)
- Test: `test_formats_hoppscotch.py` (новый), `test_formats_registry.py` (список имён)

**Interfaces:**
- Consumes: `formats.FormatSpec`, `formats.build_collection`, `core.to_yaml` (не нужен — json).
- Produces: `formats.hoppscotch`: `to_hoppscotch(collection) -> dict`, `to_hoppscotch_environments(collection) -> list[dict]`, `write_hoppscotch(collection, out) -> (file_count, note)`, `matches(path)`, `validate(path, schema_override=None)`; `HOPPSCOTCH_SPEC`.

- [ ] **Step 1: Write the failing test**

`test_formats_hoppscotch.py`:

```python
import json
import pathlib
import tempfile
import unittest

from test_generate_collection import COLLECTION

from formats import FORMATS
from formats import hoppscotch as h


class TestHoppscotch(unittest.TestCase):
    def test_collection_structure(self):
        doc = h.to_hoppscotch(COLLECTION)
        self.assertEqual(doc["v"], 12)
        self.assertEqual(doc["name"], "VK API")
        self.assertEqual(doc["auth"], {"authType": "bearer", "authActive": True, "token": "<<accessToken>>"})
        folder = doc["folders"][0]
        self.assertEqual(folder["v"], 12)
        self.assertEqual(folder["name"], "Users")
        self.assertEqual(folder["description"], COLLECTION["items"][0]["docs"])
        req = folder["requests"][0]
        self.assertEqual(req["v"], "17")
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["endpoint"], "<<baseUrl>>/method/users.get")
        self.assertEqual(
            req["body"],
            {"contentType": "application/x-www-form-urlencoded", "body": "user_ids: \nfields: bdate\nv: <<apiVersion>>"},
        )
        self.assertEqual(req["description"], COLLECTION["items"][0]["items"][0]["docs"])
        self.assertEqual(req["auth"], {"authType": "inherit", "authActive": True})

    def test_environment_secrets(self):
        envs = h.to_hoppscotch_environments(COLLECTION)
        self.assertEqual(len(envs), 1)
        variables = {v["key"]: v for v in envs[0]["variables"]}
        self.assertEqual(variables["accessToken"]["secret"], True)
        self.assertEqual(variables["baseUrl"]["secret"], False)
        self.assertEqual(envs[0]["v"], 2)

    def test_write_and_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "hoppscotch"
            file_count, note = h.write_hoppscotch(COLLECTION, out)
            self.assertEqual(file_count, 2)
            self.assertEqual(note, " +1 environment file(s)")
            coll = json.loads((out / "vk-api.hoppscotch.json").read_text(encoding="utf-8"))
            self.assertEqual(coll["name"], "VK API")
            env = json.loads((out / "api.vk.ru.hoppscotch.env.json").read_text(encoding="utf-8"))
            self.assertEqual(env[0]["name"], "api.vk.ru")
            self.assertEqual(h.matches(out / "vk-api.hoppscotch.json"), True)
            self.assertEqual(h.matches(out / "api.vk.ru.hoppscotch.env.json"), True)
            self.assertEqual(h.matches(out / "x.json"), False)
            self.assertEqual(h.validate(out / "vk-api.hoppscotch.json"), (1, 1))


if __name__ == "__main__":
    unittest.main()
```

`test_formats_registry.py`: `test_five_formats_registered` → список `"bundled", "hoppscotch, "insomnia"`-pending — актуальный на момент задачи: `["bundled", "hoppscotch", "openapi", "postman", "postman-v3", "tree"]`; `test_default_out_paths` += `FORMATS["hoppscotch"].default_out == "dist/hoppscotch"`.

Run: `python3 -m unittest test_formats_hoppscotch -v` — Expected: FAIL (no module).

- [ ] **Step 2: Implement module**

```python
import json
import pathlib

from formats import FormatSpec, build_collection

INHERIT = {"authType": "inherit", "authActive": True}
CONTENT_TYPES = {"form-urlencoded": "application/x-www-form-urlencoded"}


def _var(value):
    return value.replace("{{", "<<").replace("}}", ">>")


def _body_string(rows):
    return "\n".join(f"{r['name']}: {_var(r.get('value', ''))}" for r in rows)


def hoppscotch_request(req):
    info = req["info"]
    body = req.get("http", {}).get("body", {})
    return {
        "v": "17",
        "name": info["name"],
        "method": req["http"]["method"],
        "endpoint": _var(req["http"]["url"]),
        "params": [],
        "headers": [],
        "auth": INHERIT,
        "body": {"contentType": CONTENT_TYPES.get(body.get("type"), body.get("type")), "body": _body_string(body.get("data", []))},
        "requestVariables": [],
        "responses": {},
        "preRequestScript": "",
        "testScript": "",
        "description": req.get("docs") or info.get("description") or "",
    }


def hoppscotch_folder(folder):
    return {
        "v": 12,
        "name": folder["info"]["name"],
        "folders": [],
        "requests": [hoppscotch_request(r) for r in folder.get("items", [])],
        "auth": INHERIT,
        "headers": [],
        "variables": [],
        "description": folder.get("docs") or folder["info"].get("description") or "",
        "preRequestScript": "",
        "testScript": "",
    }


def to_hoppscotch(collection):
    auth = collection["request"]["auth"]
    return {
        "v": 12,
        "name": collection["info"]["name"],
        "folders": [hoppscotch_folder(f) for f in collection.get("items", [])],
        "requests": [],
        "auth": {"authType": "bearer", "authActive": True, "token": _var(auth["token"])},
        "headers": [],
        "variables": [],
        "description": collection.get("docs") or "",
        "preRequestScript": "",
        "testScript": "",
    }


def to_hoppscotch_environments(collection):
    out = []
    for env in collection.get("config", {}).get("environments", []):
        variables = [
            {"key": v["name"], "initialValue": v.get("value", ""), "currentValue": v.get("value", ""), "secret": bool(v.get("secret"))}
            for v in env.get("variables", [])
        ]
        out.append({"v": 2, "id": env["name"], "name": env["name"], "variables": variables})
    return out


def write_hoppscotch(collection, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / "vk-api.hoppscotch.json").write_text(json.dumps(to_hoppscotch(collection), ensure_ascii=False, indent=2), encoding="utf-8")
    envs = to_hoppscotch_environments(collection)
    for env in envs:
        (out / f"{env['name']}.hoppscotch.env.json").write_text(json.dumps([env], ensure_ascii=False, indent=2), encoding="utf-8")
    note = f" +{len(envs)} environment file(s)" if envs else ""
    return 1 + len(envs), note


def matches(path):
    return ".hoppscotch." in pathlib.Path(path).name and path.name.endswith(".json")


def validate(path, schema_override=None):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, list):
        doc = doc[0]
    if doc.get("v") == 2:
        return 0, len(doc.get("variables", []))
    folders = doc.get("folders", [])
    requests = sum(len(f.get("requests", [])) for f in folders) + len(doc.get("requests", []))
    return len(folders), requests


HOPPSCOTCH_SPEC = FormatSpec(
    name="hoppscotch",
    default_out="dist/hoppscotch",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_hoppscotch,
    matches=matches,
    validate=validate,
)
```

`formats/__init__.py`: `from formats import hoppscotch as _hoppscotch` + `"hoppscotch": _hoppscotch.HOPPSCOTCH_SPEC` (после postman, перед postman-v3 — порядок только перечисления). `validate_collection.py`: `SNIFF_PRIORITY = ("openapi", "hoppscotch", "postman", "postman-v3", "bundled", "tree")`; ветка:
```python
    if spec.name == "hoppscotch":
        folders, requests = spec.validate(args.path)
        print(f"OK: hoppscotch, {folders} folders, {requests} requests, 0 structural violations")
        return None
```

- [ ] **Step 3: E2E golden (в test_merge_collection.py TestCliPrintGolden или новый test_formats_hoppscotch)**

```python
    def test_hoppscotch_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            line = self.run_and_capture(["generate_collection.py", "--schema-dir", str(schema), "--out", str(root / "h"), "--format", "hoppscotch", "--api-version", "5.199"]).strip()
            self.assertTrue(re.fullmatch(r"format=hoppscotch folders=\d+ requests=\d+ files=\d+ collisions=\d+ encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \+\d+ environment file\(s\) \(\d+\.\d MB\)", line), line)
```
(добавляется в существующий TestCliPrintGolden в test_merge_collection.py — там уже есть run_and_capture/write_mini_schema).

- [ ] **Step 4: Run full suite**

Run: `python3 -m unittest discover -p "test_*.py"` — Expected: все OK (95 + 5 новых: 4 unit/e2e + 1 golden; точный счёт — по прогону, все зелёные).

- [ ] **Step 5: Commit**

```bash
git add formats/ validate_collection.py test_formats_hoppscotch.py test_formats_registry.py test_merge_collection.py
git commit -m "feat: hoppscotch export (collection v12/request v17 + env v2 with secret flags) behind the format registry"
```

---

### Task 2: `formats/insomnia.py` — v4 JSON

**Files:**
- Create: `formats/insomnia.py`
- Modify: `formats/__init__.py`, `validate_collection.py`
- Test: `test_formats_insomnia.py`, `test_formats_registry.py`

**Interfaces:**
- Produces: `to_insomnia(collection) -> dict`, `write_insomnia(collection, out) -> (1, "")`, `matches`, `validate`, `INSOMNIA_SPEC`; default_out `dist/insomnia/vk-api.insomnia.json`.

- [ ] **Step 1: Verify open detail against importer source (freeze эталон)**

webfetch `https://raw.githubusercontent.com/Kong/insomnia/develop/packages/insomnia/src/main/importers/importers/insomnia-4.ts`: подтвердить (а) форму auth-объекта у request_group (ожидаем `authentication: {type: "bearer", token, prefix?}`), (б) поддержку `kvPairData` у environment (массив `{name, value, type: "secret"|"str", enabled}`) при импорте. Если форма иная — привести код Step 2 к источнику и зафиксировать в отчёте; эталонный тест ниже закрепляет выбор.

- [ ] **Step 2: Write the failing test**

`test_formats_insomnia.py`:

```python
import json
import pathlib
import tempfile
import unittest

from test_generate_collection import COLLECTION

from formats import FORMATS
from formats import insomnia as ins


class TestInsomnia(unittest.TestCase):
    def test_export_structure(self):
        doc = ins.to_insomnia(COLLECTION)
        self.assertEqual(doc["_type"], "export")
        self.assertEqual(doc["__export_format"], 4)
        types = [r["_type"] for r in doc["resources"]]
        self.assertEqual(types.count("workspace"), 1)
        self.assertEqual(types.count("environment"), 1)
        self.assertEqual(types.count("request_group"), 2)
        self.assertEqual(types.count("request"), 1)
        groups = [r for r in doc["resources"] if r["_type"] == "request_group"]
        root = [g for g in groups if g["parentId"] == "__WORKSPACE_ID__"][0]
        self.assertEqual(root["name"], "VK API")
        self.assertEqual(root["authentication"]["type"], "bearer")
        self.assertEqual(root["authentication"]["token"], "{{ accessToken }}")
        folder = [g for g in groups if g["parentId"] != "__WORKSPACE_ID__"][0]
        self.assertEqual(folder["name"], "Users")
        req = [r for r in doc["resources"] if r["_type"] == "request"][0]
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["url"], "{{ baseUrl }}/method/users.get")
        self.assertEqual(req["body"]["mimeType"], "application/x-www-form-urlencoded")
        params = req["body"]["params"]
        self.assertEqual(params[0]["name"], "user_ids")
        self.assertEqual(params[1]["name"], "fields")
        self.assertEqual(params[1]["disabled"], True)
        env = [r for r in doc["resources"] if r["_type"] == "environment"][0]
        kv = {v["name"]: v for v in env.get("kvPairData", [])}
        self.assertEqual(kv["accessToken"]["type"], "secret")
        self.assertEqual(kv["baseUrl"]["type"], "str")

    def test_write_matches_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api.insomnia.json"
            file_count, note = ins.write_insomnia(COLLECTION, out)
            self.assertEqual((file_count, note), (1, ""))
            self.assertEqual(ins.matches(out), True)
            self.assertEqual(ins.matches(pathlib.Path("vk-api.json")), False)
            self.assertEqual(ins.validate(out), (1, 1))


if __name__ == "__main__":
    unittest.main()
```

Registry-тесты: список += `"insomnia"`; default_out += `dist/insomnia/vk-api.insomnia.json`.

Run: `python3 -m unittest test_formats_insomnia -v` — Expected: FAIL (no module).

- [ ] **Step 3: Implement module**

```python
import json
import pathlib

from formats import FormatSpec, build_collection


def _params(rows):
    out = []
    for i, r in enumerate(rows):
        param = {"id": f"__P_{i}__", "name": r["name"], "value": r.get("value", "")}
        if r.get("description"):
            param["description"] = r["description"]
        if r.get("disabled"):
            param["disabled"] = True
        out.append(param)
    return out


def to_insomnia(collection):
    resources = [
        {"_id": "__WORKSPACE_ID__", "_type": "workspace", "name": collection["info"]["name"], "scope": "collection"},
    ]
    for env in collection.get("config", {}).get("environments", []):
        data = {v["name"]: v.get("value", "") for v in env.get("variables", [])}
        kv = [
            {"id": f"__KVP_{i}__", "name": v["name"], "value": v.get("value", ""), "type": "secret" if v.get("secret") else "str", "enabled": True}
            for i, v in enumerate(env.get("variables", []))
        ]
        resources.append(
            {
                "_id": "__ENV_1__",
                "_type": "environment",
                "parentId": "__BASE_ENVIRONMENT_ID__",
                "name": "Base Environment",
                "data": data,
                "dataPropertyOrder": {".": [v["name"] for v in env.get("variables", [])]},
                "kvPairData": kv,
            }
        )
    resources.append(
        {
            "_id": "__GRP_0__",
            "_type": "request_group",
            "parentId": "__WORKSPACE_ID__",
            "name": collection["info"]["name"],
            "description": collection.get("docs") or "",
            "authentication": {"type": "bearer", "token": collection["request"]["auth"]["token"], "prefix": ""},
        }
    )
    for i, folder in enumerate(collection.get("items", []), start=1):
        resources.append(
            {
                "_id": f"__GRP_{i}__",
                "_type": "request_group",
                "parentId": "__GRP_0__",
                "name": folder["info"]["name"],
                "description": folder.get("docs") or folder["info"].get("description") or "",
            }
        )
        for j, req in enumerate(folder.get("items", [])):
            http = req["http"]
            resources.append(
                {
                    "_id": f"__REQ_{i}_{j}__",
                    "_type": "request",
                    "parentId": f"__GRP_{i}__",
                    "name": req["info"]["name"],
                    "method": http["method"],
                    "url": http["url"],
                    "body": {"mimeType": "application/x-www-form-urlencoded", "params": _params(http.get("body", {}).get("data", []))},
                    "description": req.get("docs") or req["info"].get("description") or "",
                }
            )
    return {"_type": "export", "__export_format": 4, "resources": resources}


def write_insomnia(collection, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(to_insomnia(collection), ensure_ascii=False, indent=2), encoding="utf-8")
    return 1, ""


def matches(path):
    name = pathlib.Path(path).name
    return "insomnia" in name and name.endswith(".json")


def validate(path, schema_override=None):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if doc.get("_type") != "export" or doc.get("__export_format") != 4:
        raise ValueError(f"not an insomnia v4 export: {path}")
    types = [r["_type"] for r in doc.get("resources", [])]
    return types.count("request_group") - 1, types.count("request")


INSOMNIA_SPEC = FormatSpec(
    name="insomnia",
    default_out="dist/insomnia/vk-api.insomnia.json",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_insomnia,
    matches=matches,
    validate=validate,
)
```

(если Step 1 дал иную форму auth/kvPairData — скорректировать по источнику; ассерты теста обновить синхронно с источником.)

`formats/__init__.py` += регистрация; `validate_collection.py`: `SNIFF_PRIORITY` вставить `"insomnia"` после `"openapi"`; ветка печати `OK: insomnia v4, {folders} folders, {requests} requests, 0 structural violations`.

- [ ] **Step 4: Golden e2e + full suite**

Golden (в TestCliPrintGolden): `--format insomnia --out <root>/i.json` → `re.fullmatch(r"format=insomnia folders=\d+ requests=\d+ files=\d+ collisions=\d+ encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \(\d+\.\d MB\)", line)`.
Run: `python3 -m unittest discover -p "test_*.py"` — все OK.

- [ ] **Step 5: Commit**

```bash
git add formats/ validate_collection.py test_formats_insomnia.py test_formats_registry.py test_merge_collection.py
git commit -m "feat: insomnia v4 JSON export (secret kvPairData, bearer on root request_group) behind the format registry"
```

---

### Task 3: `formats/yaak.py` — sync-папка + merge

**Files:**
- Create: `formats/yaak.py`
- Modify: `formats/__init__.py`, `validate_collection.py`
- Test: `test_formats_yaak.py`, `test_formats_registry.py`, `test_merge_collection.py`

**Interfaces:**
- Consumes: `core.to_yaml`, `core.require_yaml`, `merge_collection.merge`.
- Produces: `yaak_resources(collection) -> list[(id, doc)]`, `write_yaak`, `load_yaak(out) -> collection | None`, `yaak_prune_orphans(out, collection) -> list[Path]`, `matches`, `validate`, `YAAK_SPEC` (`supports_merge=True`, `keep_old_items=True`); default_out `dist/yaak/vk-api`.

- [ ] **Step 1: Write the failing test**

`test_formats_yaak.py`:

```python
import pathlib
import tempfile
import unittest

from test_generate_collection import COLLECTION

from formats import FORMATS
from formats import yaak as y


class TestYaak(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def test_resources_structure(self):
        resources = dict(y.yaak_resources(COLLECTION))
        self.assertEqual(resources["wrk_1"]["model"], "workspace")
        self.assertEqual(resources["wrk_1"]["authenticationType"], "bearer")
        self.assertEqual(resources["wrk_1"]["authentication"]["token"], "${[ env.accessToken ]}")
        self.assertEqual(resources["env_1"]["model"], "environment")
        self.assertEqual(resources["fl_1"]["model"], "folder")
        self.assertEqual(resources["fl_1"]["workspaceId"], "wrk_1")
        req = resources["rq_1"]
        self.assertEqual(req["model"], "http_request")
        self.assertEqual(req["url"], "${[ env.baseUrl ]}/method/users.get")
        self.assertEqual(req["bodyType"], "application/x-www-form-urlencoded")
        self.assertEqual(
            req["body"]["form"],
            [
                {"name": "user_ids", "value": "", "enabled": True},
                {"name": "fields", "value": "bdate", "enabled": False},
                {"name": "v", "value": "${[ env.apiVersion ]}", "enabled": True},
            ],
        )

    def test_write_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api"
            file_count, note = y.write_yaak(COLLECTION, out)
            self.assertEqual((file_count, note), (4, ""))
            loaded = y.load_yaak(out)
            self.assertEqual(loaded["info"]["name"], "VK API")
            folder = loaded["items"][0]
            self.assertEqual(folder["info"]["name"], "Users")
            self.assertEqual([r["info"]["name"] for r in folder["items"]], ["users.get"])
            row = folder["items"][0]["http"]["body"]["data"][1]
            self.assertEqual(row, {"name": "fields", "value": "bdate", "disabled": True})
            env = loaded["config"]["environments"][0]
            self.assertEqual([v["name"] for v in env["variables"]], ["baseUrl", "apiVersion", "accessToken", "groupToken"])

    def test_merge_e2e(self):
        from test_merge_collection import run_main, write_mini_schema

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema_dir = write_mini_schema(root / "schema")
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema_dir), "--out", str(out), "--format", "yaak", "--api-version", "5.199"])
            req_files = sorted(out.glob("yaak.rq_*.yaml"))
            import yaml
            from core import to_yaml
            doc = yaml.safe_load(req_files[0].read_text(encoding="utf-8"))
            doc["body"]["form"][0]["value"] = "1,2"
            req_files[0].write_text(to_yaml(doc), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema_dir), "--out", str(out), "--format", "yaak", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(req_files[0].read_text(encoding="utf-8"))
            self.assertEqual(doc["body"]["form"][0]["value"], "1,2")
            v_row = [r for r in doc["body"]["form"] if r["name"] == "v"][0]
            self.assertEqual(v_row["value"], "${[ env.apiVersion ]}")

    def test_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api"
            y.write_yaak(COLLECTION, out)
            stray = out / "yaak.rq_999.yaml"
            stray.write_text("model: http_request\nid: rq_999\n", encoding="utf-8")
            removed = y.yaak_prune_orphans(out, COLLECTION)
            self.assertFalse(stray.exists())
            self.assertEqual(len(removed), 1)

    def test_matches_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api"
            y.write_yaak(COLLECTION, out)
            self.assertEqual(y.matches(out), True)
            self.assertEqual(y.matches(pathlib.Path("/tmp")), False)
            self.assertEqual(y.validate(out), (1, 1))


if __name__ == "__main__":
    unittest.main()
```

(В test_merge_e2e helpers `write_mini_schema`/`run_main` импортируются из test_merge_collection — как в существующих e2e.)

Registry-тесты: список += `"yaak"`; merge-матрица += `"yaak"`; default_out += `dist/yaak/vk-api`.

- [ ] **Step 2: Implement module**

```python
import pathlib
import re

from core import require_yaml, to_yaml
from formats import FormatSpec, build_collection

TO_YAAK = re.compile(r"\{\{(\w+)\}\}")
FROM_YAAK = re.compile(r"\$\{\[\s*env\.(\w+)\s*\]\}")


def _yak(value):
    return TO_YAAK.sub(lambda m: "${[ env." + m.group(1) + " ]}", value)


def _unyak(value):
    return FROM_YAAK.sub(lambda m: "{{" + m.group(1) + "}}", value)


def yaak_resources(collection):
    resources = []
    auth = collection["request"]["auth"]
    resources.append(
        (
            "wrk_1",
            {
                "model": "workspace",
                "id": "wrk_1",
                "name": collection["info"]["name"],
                "description": collection.get("docs") or "",
                "authenticationType": "bearer",
                "authentication": {"token": _yak(auth["token"])},
            },
        )
    )
    for i, env in enumerate(collection.get("config", {}).get("environments", []), start=1):
        resources.append(
            (
                f"env_{i}",
                {
                    "model": "environment",
                    "id": f"env_{i}",
                    "name": env["name"],
                    "public": True,
                    "parentModel": "workspace",
                    "parentId": "wrk_1",
                    "variables": [{"name": v["name"], "value": v.get("value", ""), "enabled": True} for v in env.get("variables", [])],
                },
            )
        )
    rq = 0
    for i, folder in enumerate(collection.get("items", []), start=1):
        resources.append(
            (
                f"fl_{i}",
                {
                    "model": "folder",
                    "id": f"fl_{i}",
                    "workspaceId": "wrk_1",
                    "folderId": None,
                    "name": folder["info"]["name"],
                    "description": folder.get("docs") or folder["info"].get("description") or "",
                },
            )
        )
        for j, req in enumerate(folder.get("items", []), start=1):
            rq += 1
            http = req.get("http", {})
            resources.append(
                (
                    f"rq_{rq}",
                    {
                        "model": "http_request",
                        "id": f"rq_{rq}",
                        "workspaceId": "wrk_1",
                        "folderId": f"fl_{i}",
                        "name": req["info"]["name"],
                        "method": http.get("method", "POST"),
                        "url": _yak(http.get("url", "")),
                        "bodyType": "application/x-www-form-urlencoded",
                        "body": {
                            "form": [
                                {"name": r["name"], "value": _yak(r.get("value", "")), "enabled": not r.get("disabled")}
                                for r in http.get("body", {}).get("data", [])
                            ]
                        },
                        "description": req.get("docs") or req["info"].get("description") or "",
                    },
                )
            )
    return resources


def write_yaak(collection, out):
    out.mkdir(parents=True, exist_ok=True)
    resources = yaak_resources(collection)
    for rid, doc in resources:
        (out / f"yaak.{rid}.yaml").write_text(to_yaml(doc), encoding="utf-8")
    return len(resources), ""


def load_yaak(out):
    out = pathlib.Path(out)
    files = sorted(out.glob("yaak.*.yaml"))
    if not files:
        return None
    yaml = require_yaml()
    docs = [d for d in (yaml.safe_load(f.read_text(encoding="utf-8")) for f in files) if isinstance(d, dict)]
    workspace = next((d for d in docs if d.get("model") == "workspace"), None)
    if workspace is None:
        return None
    folders = [d for d in docs if d.get("model") == "folder"]
    requests = [d for d in docs if d.get("model") == "http_request"]
    items = []
    for folder in sorted(folders, key=lambda d: d.get("id", "")):
        children = [r for r in requests if r.get("folderId") == folder.get("id")]
        items.append(
            {
                "info": {"name": folder.get("name", ""), "type": "folder", "description": folder.get("description")},
                "request": {"auth": "inherit"},
                "items": [
                    {
                        "info": {"name": r.get("name", ""), "type": "http", "description": r.get("description")},
                        "http": {
                            "method": r.get("method", "POST"),
                            "url": _unyak(r.get("url", "")),
                            "auth": "inherit",
                            "body": {
                                "type": "form-urlencoded",
                                "data": [
                                    {"name": p["name"], "value": _unyak(p.get("value", "")), **({"disabled": True} if not p.get("enabled", True) else {})}
                                    for p in (r.get("body") or {}).get("form", [])
                                ],
                            },
                        },
                        "docs": r.get("description"),
                    }
                    for r in children
                ],
                "docs": folder.get("description"),
            }
        )
    envs = []
    for env in [d for d in docs if d.get("model") == "environment"]:
        envs.append(
            {
                "name": env.get("name", ""),
                "variables": [{"name": v["name"], "value": v.get("value", "")} for v in env.get("variables", [])],
            }
        )
    return {
        "opencollection": "1.0.0",
        "info": {"name": workspace.get("name", ""), "description": workspace.get("description", "")},
        "request": {"auth": {"type": "bearer", "token": _unyak((workspace.get("authentication") or {}).get("token", ""))}},
        "config": {"environments": envs},
        "items": items,
        "docs": workspace.get("description", ""),
    }


def yaak_prune_orphans(out, collection):
    out = pathlib.Path(out)
    keep = {rid for rid, _ in yaak_resources(collection)}
    removed = []
    for f in sorted(out.glob("yaak.*.yaml")):
        rid = f.name[len("yaak.") : -len(".yaml")]
        if rid not in keep:
            f.unlink()
            removed.append(f)
    return removed


def matches(path):
    path = pathlib.Path(path)
    return path.is_dir() and any(path.glob("yaak.*.yaml"))


def validate(path, schema_override=None):
    yaml = require_yaml()
    docs = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted(pathlib.Path(path).glob("yaak.*.yaml"))]
    models = [d.get("model") for d in docs if isinstance(d, dict)]
    if any(m not in ("workspace", "environment", "folder", "http_request") for m in models):
        raise ValueError(f"unexpected yaak models in {path}")
    return models.count("folder"), models.count("http_request")


YAAK_SPEC = FormatSpec(
    name="yaak",
    default_out="dist/yaak/vk-api",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_yaak,
    supports_merge=True,
    load_existing=load_yaak,
    prune_orphans=yaak_prune_orphans,
    keep_old_items=True,
    matches=matches,
    validate=validate,
)
```

`formats/__init__.py` += регистрация; `validate_collection.py`: `SNIFF_PRIORITY` += `"yaak"` (после postman-v3, перед bundled); ветка `OK: yaak, {folders} folders, {requests} requests, 0 structural violations`.

- [ ] **Step 3: Golden e2e + merge e2e через main + full suite**

Golden: `--format yaak --out <root>/yk` → full-line regex (folders/requests, без note). Run: `python3 -m unittest discover -p "test_*.py"` — все OK.

- [ ] **Step 4: Commit**

```bash
git add formats/ validate_collection.py test_formats_yaak.py test_formats_registry.py test_merge_collection.py
git commit -m "feat: yaak sync-folder export with --merge support (deterministic yaak.<id>.yaml resources, full round-trip loader, orphan prune)"
```

---

### Task 4: `formats/insomnia_v5.py` — research-freeze + генерация

**Files:**
- Create: `formats/insomnia_v5.py`
- Modify: `formats/__init__.py`, `validate_collection.py`
- Test: `test_formats_insomnia_v5.py`, `test_formats_registry.py`

**Interfaces:**
- Produces: `write_insomnia_v5(collection, out) -> (file_count, "")`, `matches`, `validate`, `INSOMNIA_V5_SPEC` (БЕЗ merge — поля не заполняются в этой задаче); default_out `dist/insomnia/vk-api-local`.

- [ ] **Step 1: Research-freeze layout**

webfetch:
- `https://raw.githubusercontent.com/Kong/insomnia/develop/packages/insomnia/src/common/insomnia-v5.ts`
- `https://raw.githubusercontent.com/Kong/insomnia/develop/packages/insomnia/src/common/import-v5-parser.ts`
- при необходимости поиск по репо Kong/insomnia: git-sync layout (имена файлов в папке синка, например по `insomnia-sync`/`git-storage`).

Зафиксировать в отчёте задачи: (а) имя/имена файлов v5-коллекции в git-sync папке; (б) точную схему YAML (ключи collection/environments/cookieJar, форма запроса/папки внутри дерева). Эталон всех последующих ассертов — эти источники.

- [ ] **Step 2: Write the failing test (по зафиксированному layout)**

Минимальный каркас `test_formats_insomnia_v5.py` (ассерты уточняются по Step 1, сохранить интент):

```python
import json
import pathlib
import tempfile
import unittest

from test_generate_collection import COLLECTION

from formats import FORMATS
from formats import insomnia_v5 as v5


class TestInsomniaV5(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def test_write_produces_v5_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api-local"
            file_count, note = v5.write_insomnia_v5(COLLECTION, out)
            self.assertEqual(note, "")
            files = sorted(p for p in out.rglob("*.yaml") if p.is_file())
            self.assertTrue(files)
            import yaml
            doc = yaml.safe_load(files[0].read_text(encoding="utf-8"))
            self.assertIn("collection.insomnia.rest/5.0", str(doc.get("type", "")))
            self.assertEqual(doc.get("name"), "VK API")
            self.assertEqual(v5.matches(out), True)
            self.assertEqual(v5.validate(out)[1], doc_counts_requests(doc))


if __name__ == "__main__":
    unittest.main()
```

(`doc_counts_requests` — хелпер по зафиксированной схеме; подсчёт запросов в дереве.)

Registry: список += `"insomnia-v5"`; default_out += `dist/insomnia/vk-api-local`.

- [ ] **Step 3: Implement (структура по Step 1; ниже — каркас по research-данным)**

```python
import pathlib

from core import require_yaml, to_yaml
from formats import FormatSpec, build_collection


def _v5_request(req):
    http = req["http"]
    params = []
    for i, r in enumerate(http.get("body", {}).get("data", [])):
        p = {"id": f"req_param_{i}", "name": r["name"], "value": r.get("value", "")}
        if r.get("description"):
            p["description"] = r["description"]
        if r.get("disabled"):
            p["disabled"] = True
        params.append(p)
    return {
        "_id": req["info"]["name"],
        "name": req["info"]["name"],
        "method": http["method"],
        "url": http["url"],
        "body": {"mimeType": "application/x-www-form-urlencoded", "params": params},
        "description": req.get("docs") or req["info"].get("description") or "",
    }


def to_insomnia_v5(collection):
    folders = []
    for folder in collection.get("items", []):
        folders.append(
            {
                "name": folder["info"]["name"],
                "description": folder.get("docs") or folder["info"].get("description") or "",
                "children": [_v5_request(r) for r in folder.get("items", [])],
            }
        )
    environments = []
    for env in collection.get("config", {}).get("environments", []):
        environments.append(
            {"name": env["name"], "data": {v["name"]: v.get("value", "") for v in env.get("variables", [])}}
        )
    return {
        "type": "collection.insomnia.rest/5.0",
        "name": collection["info"]["name"],
        "collection": {"folders": folders},
        "environments": environments,
        "cookieJar": {},
    }
```

`write_insomnia_v5` кладёт YAML по layout из Step 1 (один файл коллекции или per-resource — как зафиксировано); корневой Bearer — по зафиксированной схеме (например `authentication` на корневой папке v5-дерева). `matches`: is_dir и первый `*.yaml` содержит `collection.insomnia.rest/5.0`; `validate`: парсинг + счётчики (folders/requests из дерева).

`formats/__init__.py` += регистрация; `validate_collection.py` += `"insomnia-v5"` в SNIFF_PRIORITY (после yaak) + OK-ветка `OK: insomnia v5, {folders} folders, {requests} requests, 0 structural violations`.

- [ ] **Step 4: Golden e2e + full suite + commit**

Golden: `--format insomnia-v5 --out <root>/i5`. Run discover — все OK.
```bash
git add formats/ validate_collection.py test_formats_insomnia_v5.py test_formats_registry.py test_merge_collection.py
git commit -m "feat: insomnia v5 git-sync folder export (layout frozen from upstream sources) behind the format registry"
```

---

### Task 5: `insomnia-v5` merge — loader + prune

**Files:**
- Modify: `formats/insomnia_v5.py`, `test_formats_insomnia_v5.py`, `test_formats_registry.py`

**Interfaces:**
- Consumes: layout Task 4, `merge_collection.merge`.
- Produces: `load_insomnia_v5(out) -> collection | None`, `insomnia_v5_prune_orphans(out, collection) -> list[Path]`; спека получает `supports_merge=True, load_existing, prune_orphans, keep_old_items=True`.

- [ ] **Step 1: Write the failing test**

В `test_formats_insomnia_v5.py` (helpers `write_mini_schema`/`run_main` из test_merge_collection):

```python
    def test_merge_preserves_user_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema_dir = write_mini_schema(root / "schema")
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema_dir), "--out", str(out), "--format", "insomnia-v5", "--api-version", "5.199"])
            import yaml
            req_file = first_request_file(out)
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            set_first_param_value(doc, "1,2")
            from core import to_yaml
            req_file.write_text(to_yaml(doc), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema_dir), "--out", str(out), "--format", "insomnia-v5", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            self.assertEqual(get_first_param_value(doc), "1,2")

    def test_prune_removes_stray(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            v5.write_insomnia_v5(COLLECTION, out)
            stray = next(iter(out.rglob("*.yaml"))).parent / "stray.yaml"
            stray.write_text("type: collection.insomnia.rest/5.0\nname: ghost\n", encoding="utf-8")
            removed = v5.insomnia_v5_prune_orphans(out, COLLECTION)
            self.assertFalse(stray.exists())
            self.assertEqual(len(removed), 1)
```

(`first_request_file`/`set_first_param_value`/`get_first_param_value` — хелперы по layout Task 4.) Registry: merge-матрица += `"insomnia-v5"`.

- [ ] **Step 2: Implement loader/prune**

`load_insomnia_v5`: читает YAML-файлы по layout → полная модель (запросы → `{info, http{method,url,auth:inherit,body{data}}, docs}`; params → строки с disabled; папки → items; environments → config; Bearer корневой → request.auth). `insomnia_v5_prune_orphans`: файлы вне списка вывода — удалить. Спека: заполнить merge-поля.

- [ ] **Step 3: Full suite + commit**

Run: `python3 -m unittest discover -p "test_*.py"` — все OK.
```bash
git add formats/insomnia_v5.py test_formats_insomnia_v5.py test_formats_registry.py
git commit -m "feat: insomnia v5 --merge support (full round-trip loader and orphan prune for git-sync folder)"
```

---

### Task 6: README — таблица сравнения + финальный аудит

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Таблица сравнения**

Раздел «## Сравнение форматов» после «## Как добавить формат вывода» — таблица и сноски дословно из спеки (`docs/superpowers/specs/2026-09-17-new-formats-design.md`, раздел «Таблица сравнения в README»), плюс вводное предложение: «Срез на сентябрь 2026; Kreya и HTTPie не входят в генератор — см. строки».

- [ ] **Step 2: Обновить упоминания форматов**

- «Использование»: добавить примеры `python3 generate_collection.py --format yaak`, `--format insomnia`, `--format insomnia-v5`, `--format hoppscotch`.
- Дерево вывода `dist/` дополнить: `yaak/`, `insomnia/`, `hoppscotch/`.

- [ ] **Step 3: Финальный аудит**

```bash
python3 -m unittest discover -p "test_*.py"
python3 generate_collection.py --help
python3 validate_collection.py dist/yaak/vk-api 2>/dev/null || true
```
Expected: suite OK; `--format` показывает 9 вариантов; README без противоречий (сверить таблицу с фактическими спеками: merge-набор = tree/bundled/postman-v3/yaak/insomnia-v5).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: client export comparison table (secrets, docs, merge, import) and new format examples"
```

---

## Self-Review (выполнен при составлении)

- **Spec coverage:** hoppscotch (T1), insomnia v4 + kvPairData/auth-фриз (T2), yaak + merge (T3), insomnia-v5 research-freeze + генерация (T4) + merge (T5), таблица сравнения + README (T6); SNIFF_PRIORITY/OK-ветки — в T1-T4; контрактные тесты реестра — в каждой задаче; golden — в T1-T4. «Не входит» (Kreya/HTTPie/CI) — соблюдено.
- **Placeholder scan:** два research-freeze шага (T2 Step 1, T4 Step 1) — явные механизмы закрытия (источники + эталонные тесты), не TBD; каркасы кода снабжены интентами и ссылками.
- **Type consistency:** `write -> (file_count, note)`; `matches(path) -> bool`; `validate(path, schema_override=None) -> (folders, requests)`; `load_* -> collection | None`; `*_prune_orphans(out, collection) -> list[Path]` — единообразно с контрактом FormatSpec.
