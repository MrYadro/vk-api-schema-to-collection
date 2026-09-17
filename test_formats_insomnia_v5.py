import pathlib
import tempfile
import unittest

from test_generate_collection import COLLECTION

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
        users = root["children"][0]
        self.assertEqual(users["name"], "Users")
        self.assertNotIn("method", users)
        self.assertEqual(users["meta"]["description"], "# Users\n\n1 метод(ов) VK API.")
        req = users["children"][0]
        self.assertEqual(req["name"], "users.get")
        self.assertEqual(req["method"], "POST")
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

    def test_registered_without_merge(self):
        spec = FORMATS["insomnia-v5"]
        self.assertEqual(spec.default_out, "dist/insomnia/vk-api-local")
        self.assertEqual(spec.stats_keys, ("folders", "requests"))
        self.assertFalse(spec.supports_merge)
        self.assertIsNone(spec.load_existing)
        self.assertIsNone(spec.prune_orphans)

    def test_validate_and_sniff(self):
        from validate_collection import sniff_spec
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "i5"
            v5.write_insomnia_v5(COLLECTION, out)
            self.assertEqual(sniff_spec(out).name, "insomnia-v5")
            self.assertEqual(v5.validate(out), (1, 1))


if __name__ == "__main__":
    unittest.main()
