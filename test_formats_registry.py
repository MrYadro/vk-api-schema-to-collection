import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import generate_collection as g
from formats import FORMATS, FormatSpec, opencollection
from formats.postman_v3 import write_postman_v3
from test_generate_collection import COLLECTION
from validate_collection import sniff_spec


class TestRegistry(unittest.TestCase):
    def test_formats_registered(self):
        self.assertEqual(
            sorted(FORMATS),
            ["bundled", "hoppscotch", "insomnia", "openapi", "postman", "postman-v3", "tree"],
        )

    def test_default_out_paths(self):
        self.assertEqual(FORMATS["tree"].default_out, "dist/opencollection/vk-api")
        self.assertEqual(FORMATS["bundled"].default_out, "dist/opencollection/vk-api.yaml")
        self.assertEqual(FORMATS["postman"].default_out, "dist/postman/vk-api.postman_collection.json")
        self.assertEqual(FORMATS["postman-v3"].default_out, "dist/postman/vk-api-local")
        self.assertEqual(FORMATS["openapi"].default_out, "dist/openapi/vk-api.yaml")
        self.assertEqual(FORMATS["hoppscotch"].default_out, "dist/hoppscotch")
        self.assertEqual(FORMATS["insomnia"].default_out, "dist/insomnia/vk-api.insomnia.json")

    def test_stats_keys(self):
        self.assertEqual(FORMATS["tree"].stats_keys, ("folders", "requests"))
        self.assertEqual(FORMATS["openapi"].stats_keys, ("operations", "schemas"))

    def test_model_based_flags(self):
        for name in ("tree", "bundled", "postman", "postman-v3"):
            self.assertTrue(FORMATS[name].model_based, name)
        self.assertFalse(FORMATS["openapi"].model_based)

    def test_spec_names_match_keys(self):
        for key, spec in FORMATS.items():
            self.assertEqual(spec.name, key)


class TestMergeContract(unittest.TestCase):
    def test_merge_formats_have_loaders(self):
        for name, spec in FORMATS.items():
            if spec.supports_merge:
                self.assertIsNotNone(spec.load_existing, name)
                self.assertIsNotNone(spec.prune_orphans, name)
            else:
                self.assertIsNone(spec.load_existing, name)
                self.assertIsNone(spec.prune_orphans, name)

    def test_merge_matrix(self):
        self.assertEqual(
            {n for n, s in FORMATS.items() if s.supports_merge},
            {"tree", "bundled", "postman-v3"},
        )
        self.assertFalse(FORMATS["postman-v3"].keep_old_items)
        self.assertTrue(FORMATS["tree"].keep_old_items)

    def test_merge_flag_rejected_for_postman_and_openapi(self):
        for fmt in ("postman", "openapi"):
            with self.subTest(fmt=fmt):
                with mock.patch.object(sys, "argv", ["generate_collection.py", "--format", fmt, "--merge"]):
                    with self.assertRaises(SystemExit) as cm:
                        g.main()
                    self.assertEqual(cm.exception.code, 2)


class TestMatchesTargets(unittest.TestCase):
    def test_six_validation_targets(self):
        self.assertEqual(sniff_spec(pathlib.Path("vk-api.postman_collection.json")).name, "postman")
        self.assertEqual(sniff_spec(pathlib.Path("vk-api.postman_environment.json")).name, "postman")
        self.assertEqual(sniff_spec(pathlib.Path("dist/openapi/vk-api.yaml")).name, "openapi")
        self.assertEqual(sniff_spec(pathlib.Path("vk-api.openapi.yaml")).name, "openapi")
        self.assertEqual(sniff_spec(pathlib.Path("vk-api.yaml")).name, "bundled")
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            write_postman_v3(COLLECTION, out)
            self.assertEqual(sniff_spec(out).name, "postman-v3")
            tree_out = pathlib.Path(tmp) / "tree"
            opencollection.write_tree(COLLECTION, tree_out)
            self.assertEqual(sniff_spec(tree_out).name, "tree")


if __name__ == "__main__":
    unittest.main()
