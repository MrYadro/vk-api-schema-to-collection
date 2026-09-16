import pathlib
import tempfile
import unittest

import validate_collection as v
from generate_collection import write_postman_v3
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
            folders, requests = v.validate_postman_v3(out)
            self.assertEqual((folders, requests), (1, 1))


if __name__ == "__main__":
    unittest.main()
