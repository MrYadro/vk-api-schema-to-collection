import copy
import json
import pathlib
import re
import sys
import tempfile
import unittest

import core
import merge_collection as m
from formats import FORMATS, opencollection, postman_v3
from test_generate_collection import COLLECTION as BASE_COLLECTION
from test_generate_collection import MINI_SCHEMA


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

    def test_user_http_keys_preserved(self):
        new = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old["items"][0]["items"][0]["http"]["headers"] = {"X-Debug": "1"}
        old["items"][0]["items"][0]["http"]["url"] = "{{baseUrl}}/method/old.url"
        merged, _ = m.merge(new, old)
        http = merged["items"][0]["items"][0]["http"]
        self.assertEqual(http["headers"], {"X-Debug": "1"})
        self.assertEqual(http["url"], "{{baseUrl}}/method/users.get")

    def test_v3_unsafe_regex_synced_with_writer(self):
        names = ["Users", "a/b", "c\\d", "e:f", "Проверка", "execute (песочница)", "x y"]
        for name in names:
            self.assertEqual(m.V3_UNSAFE.sub("_", name), postman_v3.POSTMAN_V3_UNSAFE_FILENAME.sub("_", name))

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

    def test_requests_resorted_but_meta_head_kept_curated_order(self):
        new = collection_with(folder_with([request_with_rows([{"name": "v", "value": "{{apiVersion}}"}])]))
        old = collection_with(folder_with([
            request_with_rows([{"name": "v", "value": "{{apiVersion}}"}]),
            request_with_rows([{"name": "q", "value": ""}], name="users.aaa"),
        ]))
        meta_first = {"info": {"name": "zz_first", "type": "http", "seq": 1}, "http": {"body": {"data": []}}}
        meta_second = {"info": {"name": "aa_second", "type": "http", "seq": 2}, "http": {"body": {"data": []}}}
        meta = {"info": {"name": "_Meta", "type": "folder", "seq": 1}, "items": [meta_first, meta_second]}
        new["items"] = [meta, new["items"][0]]
        old["items"] = [copy.deepcopy(meta), old["items"][0]]
        merged, _ = m.merge(new, old)
        self.assertEqual([r["info"]["name"] for r in merged["items"][1]["items"]], ["users.aaa", "users.get"])
        self.assertEqual([r["info"]["name"] for r in merged["items"][0]["items"]], ["zz_first", "aa_second"])
        self.assertEqual([r["info"]["seq"] for r in merged["items"][0]["items"]], [1, 2])

    def test_collection_level_user_keys_preserved(self):
        new = new_collection()
        old = new_collection()
        old["customtop"] = {"x": 1}
        merged, _ = m.merge(new, old)
        self.assertEqual(merged["customtop"], {"x": 1})


class TestLoadBundled(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def test_round_trip(self):
        doc = {**new_collection(), "bundled": True}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.yaml"
            path.write_text(core.to_yaml(doc), encoding="utf-8")
            loaded = opencollection.load_bundled(path)
            self.assertEqual(loaded, new_collection())

    def test_missing_file_returns_none(self):
        self.assertIsNone(opencollection.load_bundled(pathlib.Path("/nonexistent/c.yaml")))


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

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api"
            opencollection.write_tree(TREE_COLLECTION, out)
            loaded = opencollection.load_tree(out)
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
        self.assertIsNone(opencollection.load_tree(pathlib.Path("/nonexistent/vk-api")))


class TestLoadPostmanV3(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def test_partial_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            postman_v3.write_postman_v3(TREE_COLLECTION, out)
            loaded = postman_v3.load_postman_v3(out)
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
        self.assertIsNone(postman_v3.load_postman_v3(pathlib.Path("/nonexistent/vk-api-local")))


class TestLoadExistingDispatch(unittest.TestCase):
    def test_dispatch(self):
        self.assertIsNone(FORMATS["openapi"].load_existing)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.yaml"
            path.write_text("info:\n  name: x\n", encoding="utf-8")
            self.assertIsNotNone(FORMATS["bundled"].load_existing(path))


def write_stray_tree_request(folder_dir, name):
    doc = {
        "info": {"name": name, "type": "http", "seq": 99},
        "http": {"method": "POST", "url": "{{baseUrl}}/method/" + name, "body": {"type": "form-urlencoded", "data": [{"name": "v", "value": "{{apiVersion}}"}]}},
    }
    (folder_dir / (name.replace(".", "_") + ".yml")).write_text(core.to_yaml(doc), encoding="utf-8")


class TestPruneOrphans(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def test_tree_removes_stray_request_and_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api"
            opencollection.write_tree(TREE_COLLECTION, out)
            users_dir = out / "Users"
            write_stray_tree_request(users_dir, "users.old")
            ghost = out / "Ghost"
            ghost.mkdir()
            (ghost / "folder.yml").write_text(core.to_yaml({"info": {"name": "Ghost", "type": "folder", "seq": 50}}), encoding="utf-8")
            removed = opencollection.tree_prune_orphans(out, TREE_COLLECTION)
            removed_names = sorted(p.name for p in removed)
            self.assertIn("users_old.yml", removed_names)
            self.assertIn("Ghost", removed_names)
            self.assertFalse((users_dir / "users.old.yml").exists())
            self.assertFalse(ghost.exists())
            self.assertTrue((users_dir / "folder.yml").exists())

    def test_postman_v3_removes_stray_request_and_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            postman_v3.write_postman_v3(TREE_COLLECTION, out)
            users_dir = out / "postman" / "collections" / "VK API" / "Users"
            stray = users_dir / "users.old.request.yaml"
            stray.write_text(core.to_yaml({"$kind": "http-request", "url": "x", "method": "POST", "body": {"type": "urlencoded", "content": []}}), encoding="utf-8")
            ghost = out / "postman" / "collections" / "VK API" / "Ghost"
            ghost.mkdir()
            removed = postman_v3.v3_prune_orphans(out, TREE_COLLECTION)
            self.assertFalse(stray.exists())
            self.assertFalse(ghost.exists())
            self.assertEqual(len(removed), 2)
            self.assertTrue((users_dir / "users.get.request.yaml").exists())


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
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.199"])
            req_file = out / "Users" / "users.get.yml"
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            doc["http"]["body"]["data"][0]["value"] = "1,2"
            req_file.write_text(core.to_yaml(doc), encoding="utf-8")
            env_file = out / "environments" / "api.vk.ru.yml"
            env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
            [v for v in env["variables"] if v["name"] == "accessToken"][0]["value"] = "tok"
            env_file.write_text(core.to_yaml(env), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            self.assertEqual(doc["http"]["body"]["data"][0]["value"], "1,2")
            v_row = [r for r in doc["http"]["body"]["data"] if r["name"] == "v"][0]
            self.assertEqual(v_row["value"], "{{apiVersion}}")
            env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
            self.assertEqual([v for v in env["variables"] if v["name"] == "accessToken"][0]["value"], "tok")
            self.assertEqual([v for v in env["variables"] if v["name"] == "apiVersion"][0]["value"], "5.200")

    def test_merge_without_existing_output_generates_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.199", "--merge"])
            self.assertTrue((out / "opencollection.yml").is_file())
            self.assertTrue((out / "Users" / "users.get.yml").is_file())

    def test_tree_merge_integration_preserves_user_edits(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.199"])
            req_file = out / "Users" / "users.get.yml"
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            doc["http"]["body"]["data"][0]["disabled"] = True
            doc["http"]["body"]["data"].insert(1, {"name": "custom", "value": "42"})
            req_file.write_text(core.to_yaml(doc), encoding="utf-8")
            custom_file = out / "Users" / "my.request.yml"
            custom_file.write_text(core.to_yaml({"info": {"name": "my.request", "type": "http", "seq": 99}, "http": {"method": "POST", "url": "{{baseUrl}}/method/my.request", "auth": "inherit", "body": {"type": "form-urlencoded", "data": [{"name": "v", "value": "{{apiVersion}}"}]}}}), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "tree", "--api-version", "5.199", "--merge"])
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            rows = {r["name"]: r for r in doc["http"]["body"]["data"]}
            self.assertTrue(rows["user_ids"].get("disabled") is True)
            self.assertEqual(rows["custom"]["value"], "42")
            self.assertTrue(custom_file.is_file())
            merged_doc = yaml.safe_load(custom_file.read_text(encoding="utf-8"))
            self.assertEqual(merged_doc["info"]["name"], "my.request")

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


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def test_bundled_merge(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            out = root / "vk-api.yaml"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "bundled", "--api-version", "5.199"])
            doc = yaml.safe_load(out.read_text(encoding="utf-8"))
            doc["config"]["environments"][0]["variables"][2]["value"] = "tok-b"
            out.write_text(core.to_yaml(doc), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "bundled", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(out.read_text(encoding="utf-8"))
            env = doc["config"]["environments"][0]["variables"]
            self.assertEqual([v for v in env if v["name"] == "accessToken"][0]["value"], "tok-b")
            self.assertEqual([v for v in env if v["name"] == "apiVersion"][0]["value"], "5.200")
            self.assertIn("bundled", doc)

    def test_postman_v3_merge_and_prune(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            schema_v2 = write_mini_schema(root / "schema2", MINI_METHODS_V2)
            out = root / "vk-api-local"
            run_main(["generate_collection.py", "--schema-dir", str(schema), "--out", str(out), "--format", "postman-v3", "--api-version", "5.199"])
            req_file = out / "postman" / "collections" / "VK API" / "Users" / "users.get.request.yaml"
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            doc["body"]["content"][0]["value"] = "1,2"
            req_file.write_text(core.to_yaml(doc), encoding="utf-8")
            env_file = out / "postman" / "environments" / "api.vk.ru.environment.yaml"
            env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
            [x for x in env["values"] if x["key"] == "accessToken"][0]["value"] = "tok-v3"
            env_file.write_text(core.to_yaml(env), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema_v2), "--out", str(out), "--format", "postman-v3", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            rows = {r["key"]: r for r in doc["body"]["content"] if isinstance(r, dict)}
            self.assertEqual(rows["user_ids"]["value"], "1,2")
            env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
            self.assertEqual([x for x in env["values"] if x["key"] == "accessToken"][0]["value"], "tok-v3")
            self.assertEqual([x for x in env["values"] if x["key"] == "apiVersion"][0]["value"], "5.200")
            old_file = out / "postman" / "collections" / "VK API" / "Users" / "users.old.request.yaml"
            self.assertTrue(old_file.exists())
            folders, requests = postman_v3.validate(out)
            self.assertEqual((folders, requests), (2, 4))
            run_main(["generate_collection.py", "--schema-dir", str(schema_v2), "--out", str(out), "--format", "postman-v3", "--api-version", "5.200", "--merge", "--prune"])
            self.assertFalse(old_file.exists())
            folders, requests = postman_v3.validate(out)
            self.assertEqual((folders, requests), (2, 3))


class TestCliPrintGolden(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def run_and_capture(self, argv):
        import generate_collection as g
        from unittest import mock
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
            self.assertIsNotNone(re.fullmatch(
                r"format=tree folders=\d+ requests=\d+ files=\d+ collisions=\d+ "
                r"encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \(\d+\.\d MB\)",
                line,
            ), line)

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
                ("bundled", ["--format", "bundled", "--out", str(root / "b.yaml"), "--schema-dir", str(schema)],
                 r"format=bundled folders=\d+ requests=\d+ files=\d+ collisions=\d+ "
                 r"encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \(\d+\.\d MB\)"),
                ("postman-v3", ["--format", "postman-v3", "--out", str(root / "v3"), "--schema-dir", str(schema)],
                 r"format=postman-v3 folders=\d+ requests=\d+ files=\d+ collisions=\d+ "
                 r"encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \(\d+\.\d MB\)"),
                ("postman", ["--format", "postman", "--out", str(root / "p.json"), "--schema-dir", str(schema)],
                 r"format=postman folders=\d+ requests=\d+ files=\d+ collisions=\d+ "
                 r"encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \+\d+ environment file\(s\) \(\d+\.\d MB\)"),
                ("openapi", ["--format", "openapi", "--out", str(root / "o.yaml"), "--schema-dir", str(openapi_root)],
                 r"format=openapi operations=\d+ schemas=\d+ files=\d+ collisions=\d+ "
                 r"encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \(\d+\.\d MB\)"),
            ]
            for fmt, argv, pattern in cases:
                with self.subTest(format=fmt):
                    line = self.run_and_capture(["generate_collection.py", *argv, "--api-version", "5.199"]).strip()
                    self.assertIsNotNone(re.fullmatch(pattern, line), line)

    def test_hoppscotch_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            line = self.run_and_capture(["generate_collection.py", "--schema-dir", str(schema), "--out", str(root / "h"), "--format", "hoppscotch", "--api-version", "5.199"]).strip()
            self.assertTrue(re.fullmatch(r"format=hoppscotch folders=\d+ requests=\d+ files=\d+ collisions=\d+ encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \+\d+ environment file\(s\) \(\d+\.\d MB\)", line), line)

    def test_yaak_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            line = self.run_and_capture(["generate_collection.py", "--schema-dir", str(schema), "--out", str(root / "yk"), "--format", "yaak", "--api-version", "5.199"]).strip()
            self.assertTrue(re.fullmatch(r"format=yaak folders=\d+ requests=\d+ files=\d+ collisions=\d+ encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \(\d+\.\d MB\)", line), line)

    def test_insomnia_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema = write_mini_schema(root / "schema")
            line = self.run_and_capture(["generate_collection.py", "--schema-dir", str(schema), "--out", str(root / "i.json"), "--format", "insomnia", "--api-version", "5.199"]).strip()
            self.assertTrue(re.fullmatch(r"format=insomnia folders=\d+ requests=\d+ files=\d+ collisions=\d+ encodings=[\w,.-]+ ru_descriptions=\d+ out=\S+ \(\d+\.\d MB\)", line), line)
