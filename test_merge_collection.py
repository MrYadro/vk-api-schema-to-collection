import copy
import unittest

import merge_collection as m


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
