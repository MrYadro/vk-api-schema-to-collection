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
