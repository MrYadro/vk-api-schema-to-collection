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


def request_with_rows(rows):
    return {
        "info": {"name": "users.get", "type": "http", "seq": 1},
        "http": {
            "method": "POST",
            "url": "{{baseUrl}}/method/users.get",
            "auth": "inherit",
            "body": {"type": "form-urlencoded", "data": rows},
        },
    }


def folder_with(reqs):
    return {"info": {"name": "Users", "type": "folder", "seq": 2}, "request": {"auth": "inherit"}, "items": reqs}


def collection_with(folder):
    c = new_collection()
    c["items"] = [folder]
    return c


class TestMergeRows(unittest.TestCase):
    def test_user_value_wins_on_diff(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True, "description": "новое"},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "bdate", "disabled": True, "description": "старое"},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        merged, stats = m.merge(new, old)
        data = merged["items"][0]["items"][0]["http"]["body"]["data"]
        self.assertEqual(data[0]["value"], "bdate")
        self.assertEqual(data[0]["description"], "новое")
        self.assertEqual(stats["preserved_values"], 1)

    def test_equal_value_replaced_silently(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
        ])]))
        _, stats = m.merge(new, old)
        self.assertEqual(stats["preserved_values"], 0)
        self.assertEqual(stats["preserved_disabled"], 0)

    def test_user_disabled_state_wins(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": ""},
        ])]))
        merged, stats = m.merge(new, old)
        row = merged["items"][0]["items"][0]["http"]["body"]["data"][0]
        self.assertNotIn("disabled", row)
        self.assertEqual(stats["preserved_disabled"], 1)

    def test_enum_group_matched_by_value(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "sort", "value": "name", "disabled": True},
            {"name": "sort", "value": "date", "disabled": True},
            {"name": "sort", "value": "id", "disabled": True},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "sort", "value": "name", "disabled": True},
            {"name": "sort", "value": "date"},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        merged, _ = m.merge(new, old)
        data = merged["items"][0]["items"][0]["http"]["body"]["data"]
        sorts = [r for r in data if r["name"] == "sort"]
        self.assertEqual([r["value"] for r in sorts], ["name", "date", "id"])
        self.assertEqual([r.get("disabled", False) for r in sorts], [True, False, True])
        self.assertEqual(data[-1]["name"], "v")

    def test_old_only_row_kept_before_v(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        old = collection_with(folder_with([request_with_rows([
            {"name": "fields", "value": "", "disabled": True},
            {"name": "custom", "value": "42", "description": "моё"},
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        merged, _ = m.merge(new, old)
        data = merged["items"][0]["items"][0]["http"]["body"]["data"]
        self.assertEqual([r["name"] for r in data], ["fields", "custom", "v"])
        self.assertEqual(data[1]["value"], "42")

    def test_missing_old_body_untouched(self):
        new = collection_with(folder_with([request_with_rows([
            {"name": "v", "value": "{{apiVersion}}"},
        ])]))
        old = collection_with(folder_with([{"info": {"name": "users.get", "type": "http", "seq": 1}}]))
        merged, stats = m.merge(new, old)
        data = merged["items"][0]["items"][0]["http"]["body"]["data"]
        self.assertEqual(data, [{"name": "v", "value": "{{apiVersion}}"}])
        self.assertEqual(stats["preserved_values"], 0)


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
