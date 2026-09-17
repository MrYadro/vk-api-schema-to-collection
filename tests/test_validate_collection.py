import pathlib
import tempfile
import unittest

import validate_collection as v
from formats import postman_v3
from formats.postman_v3 import write_postman_v3
from test_generate_collection import COLLECTION


class TestPickFormat(unittest.TestCase):
    def test_postman_collection(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api.postman_collection.json")), "postman-collection")

    def test_postman_environment(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api.postman_environment.json")), "postman-environment")

    def test_bundled_yaml(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api.yaml")), "opencollection")

    def test_tree_dir(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api")), "opencollection")

    def test_openapi_yaml(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api.openapi.yaml")), "openapi")
        self.assertEqual(v.pick_format(pathlib.Path("dist/openapi/vk-api.yaml")), "openapi")

    def test_postman_v3_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            write_postman_v3(COLLECTION, out)
            self.assertEqual(v.pick_format(out), "postman-v3")

    def test_postman_v3_validate(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml required")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            write_postman_v3(COLLECTION, out)
            folders, requests = postman_v3.validate(out)
            self.assertEqual((folders, requests), (1, 1))

    def test_postman_environment_skip_returns_none(self):
        from unittest import mock
        from formats import postman
        with tempfile.TemporaryDirectory() as tmp:
            env_path = pathlib.Path(tmp) / "x.postman_environment.json"
            env_path.write_text("{}", encoding="utf-8")
            with mock.patch("core.load_schema", side_effect=OSError):
                self.assertIsNone(postman.validate(env_path))


if __name__ == "__main__":
    unittest.main()
