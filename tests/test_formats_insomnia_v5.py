import pathlib
import tempfile
import unittest

from test_generate_collection import COLLECTION
from test_merge_collection import MINI_METHODS_V2
from test_merge_collection import run_main, write_mini_schema

from formats import FORMATS
from formats import insomnia_v5 as v5


def doc_counts_requests(doc):
    count = 0
    stack = list(doc.get("collection") or [])
    while stack:
        item = stack.pop()
        if "method" in item:
            count += 1
        else:
            stack.extend(item.get("children") or [])
    return count


def request_names(doc):
    names = []
    stack = list(doc.get("collection") or [])
    while stack:
        item = stack.pop(0)
        if not isinstance(item, dict):
            continue
        if "method" in item:
            names.append(item.get("name") or "")
        else:
            stack = list(item.get("children") or []) + stack
    return names


def first_request_file(out):
    return sorted(out.glob("insomnia.*.yaml"))[0]


def _first_request(node):
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if "method" in child:
            return child
        found = _first_request(child)
        if found is not None:
            return found
    return None


def set_first_param_value(doc, value):
    request = _first_request(doc["collection"][0])
    request["body"]["params"][0]["value"] = value


def get_first_param_value(doc):
    request = _first_request(doc["collection"][0])
    return request["body"]["params"][0]["value"]


class TestInsomniaV5(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

    def test_write_produces_git_sync_v5_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "vk-api-local"
            file_count, note = v5.write_insomnia_v5(COLLECTION, out)
            self.assertEqual(note, "")
            self.assertEqual(file_count, 1)
            files = sorted(p for p in out.rglob("*.yaml") if p.is_file())
            self.assertEqual([p.name for p in files], ["insomnia.wrk_1.yaml"])
            text = files[0].read_text(encoding="utf-8")
            self.assertEqual(text.split("\n")[0], "type: collection.insomnia.rest/5.0")
            import yaml
            doc = yaml.safe_load(text)
            self.assertEqual(doc["type"], "collection.insomnia.rest/5.0")
            self.assertEqual(doc["schema_version"], "5.1")
            self.assertEqual(doc["name"], "VK API")
            self.assertEqual(v5.matches(out), True)
            self.assertEqual(v5.validate(out)[1], doc_counts_requests(doc))

    def test_tree_schema_frozen_from_upstream(self):
        doc = v5.to_insomnia_v5(COLLECTION)
        self.assertEqual(len(doc["collection"]), 1)
        root = doc["collection"][0]
        self.assertEqual(root["name"], "VK API")
        self.assertNotIn("method", root)
        self.assertNotIn("url", root)
        self.assertEqual(
            root["authentication"],
            {"type": "bearer", "token": "{{ accessToken }}", "prefix": ""},
        )
        self.assertEqual(root["meta"]["description"], "# VK API\n\nКоллекция методов VK API.")
        self.assertEqual(root["meta"]["sortKey"], 0)
        users = root["children"][0]
        self.assertEqual(users["name"], "Users")
        self.assertNotIn("method", users)
        self.assertEqual(users["meta"]["description"], "# Users\n\n1 метод(ов) VK API.")
        self.assertEqual(users["meta"]["sortKey"], 1000)
        req = users["children"][0]
        self.assertEqual(req["name"], "users.get")
        self.assertEqual(req["method"], "POST")
        self.assertEqual(req["meta"]["sortKey"], 1000)
        self.assertTrue(req["scripts"]["afterResponse"].startswith("const body = insomnia.response.json();"))
        self.assertEqual(req["url"], "{{ baseUrl }}/method/users.get")
        self.assertEqual(req["body"]["mimeType"], "application/x-www-form-urlencoded")
        params = req["body"]["params"]
        self.assertEqual([p["name"] for p in params], ["user_ids", "fields", "v"])
        self.assertEqual(params[0]["description"], "ID пользователей")
        self.assertEqual(params[1]["disabled"], True)
        for p in params:
            self.assertNotIn("id", p)
        self.assertEqual(req["meta"]["description"], "# users.get\n\n## Параметры\n\n| Параметр |\n|---|")

    def test_environments_object_with_sub_environments(self):
        doc = v5.to_insomnia_v5(COLLECTION)
        envs = doc["environments"]
        self.assertIsInstance(envs, dict)
        self.assertEqual(envs["name"], "Base Environment")
        self.assertEqual(envs["meta"]["id"], "__ENV_1__")
        sub = envs["subEnvironments"][0]
        self.assertEqual(sub["name"], "api.vk.ru")
        self.assertEqual(sub["data"]["baseUrl"], "https://api.vk.ru")
        self.assertEqual(sub["data"]["apiVersion"], "5.199")
        self.assertEqual(
            sub["dataPropertyOrder"],
            {"&": ["baseUrl", "apiVersion", "accessToken", "groupToken"]},
        )
        self.assertEqual(sub["color"], "#0077FF")
        self.assertEqual(doc["cookieJar"]["name"], "Default Cookie Jar")

    def test_registered_with_merge(self):
        spec = FORMATS["insomnia-v5"]
        self.assertEqual(spec.default_out, "dist/insomnia/vk-api-local")
        self.assertEqual(spec.stats_keys, ("folders", "requests"))
        self.assertTrue(spec.supports_merge)
        self.assertIs(spec.load_existing, v5.load_insomnia_v5)
        self.assertIs(spec.prune_orphans, v5.insomnia_v5_prune_orphans)
        self.assertTrue(spec.keep_old_items)

    def test_validate_and_sniff(self):
        from validate_collection import sniff_spec
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "i5"
            v5.write_insomnia_v5(COLLECTION, out)
            self.assertEqual(sniff_spec(out).name, "insomnia-v5")
            self.assertEqual(v5.validate(out), (1, 1))


class TestInsomniaV5Merge(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")

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

    def test_merge_survives_unquoted_scalar_hand_edit(self):
        import yaml
        from core import to_yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema_dir = write_mini_schema(root / "schema")
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema_dir), "--out", str(out), "--format", "insomnia-v5", "--api-version", "5.199"])
            req_file = first_request_file(out)
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            set_first_param_value(doc, 123)
            req_file.write_text(to_yaml(doc), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema_dir), "--out", str(out), "--format", "insomnia-v5", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            self.assertEqual(get_first_param_value(doc), "123")

    def test_merge_updates_api_version_and_keeps_old_only(self):
        import yaml
        from core import to_yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            schema_dir = write_mini_schema(root / "schema")
            schema_v2 = write_mini_schema(root / "schema2", MINI_METHODS_V2)
            out = root / "out"
            run_main(["generate_collection.py", "--schema-dir", str(schema_dir), "--out", str(out), "--format", "insomnia-v5", "--api-version", "5.199"])
            req_file = first_request_file(out)
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            doc["environments"]["subEnvironments"][0]["data"]["accessToken"] = "tok-i5"
            req_file.write_text(to_yaml(doc), encoding="utf-8")
            run_main(["generate_collection.py", "--schema-dir", str(schema_v2), "--out", str(out), "--format", "insomnia-v5", "--api-version", "5.200", "--merge"])
            doc = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            self.assertIn("users.old", request_names(doc))
            data = doc["environments"]["subEnvironments"][0]["data"]
            self.assertEqual(data["apiVersion"], "5.200")
            self.assertEqual(data["accessToken"], "tok-i5")
            self.assertEqual(v5.validate(out), (2, 4))

    def test_load_missing_dir_returns_none(self):
        self.assertIsNone(v5.load_insomnia_v5(pathlib.Path("/nonexistent/i5")))

    def test_prune_removes_stray(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            v5.write_insomnia_v5(COLLECTION, out)
            stray = next(iter(out.rglob("*.yaml"))).parent / "stray.yaml"
            stray.write_text("type: collection.insomnia.rest/5.0\nname: ghost\n", encoding="utf-8")
            removed = v5.insomnia_v5_prune_orphans(out, COLLECTION)
            self.assertFalse(stray.exists())
            self.assertEqual(len(removed), 1)

    def test_prune_keeps_foreign_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            v5.write_insomnia_v5(COLLECTION, out)
            notes = out / "notes.yaml"
            notes.write_text("todo: buy milk\n", encoding="utf-8")
            removed = v5.insomnia_v5_prune_orphans(out, COLLECTION)
            self.assertEqual(removed, [])
            self.assertTrue(notes.is_file())
            self.assertTrue((out / v5.FILE_NAME).is_file())


if __name__ == "__main__":
    unittest.main()
