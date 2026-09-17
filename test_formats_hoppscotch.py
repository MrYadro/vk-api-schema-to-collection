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
