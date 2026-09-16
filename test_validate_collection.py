import pathlib
import unittest

import validate_collection as v


class TestPickFormat(unittest.TestCase):
    def test_postman_collection(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api.postman_collection.json")), "postman-collection")

    def test_postman_environment(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api.postman_environment.json")), "postman-environment")

    def test_bundled_yaml(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api.yaml")), "opencollection")

    def test_tree_dir(self):
        self.assertEqual(v.pick_format(pathlib.Path("vk-api")), "opencollection")


if __name__ == "__main__":
    unittest.main()
