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
