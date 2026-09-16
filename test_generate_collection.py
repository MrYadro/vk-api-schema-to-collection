import json
import pathlib
import unittest
import uuid

import generate_collection as g

POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

COLLECTION = {
    "opencollection": "1.0.0",
    "info": {
        "name": "VK API",
        "summary": "VK API methods generated from vk-api-schema",
        "version": "5.199 (2026-09-16)",
    },
    "request": {
        "auth": {"type": "bearer", "token": "{{accessToken}}"},
        "scripts": [{"type": "tests", "code": "test('x', () => {});"}],
        "variables": [
            {"name": "baseUrl", "value": "https://api.vk.ru", "description": "Базовый URL"},
            {"name": "apiVersion", "value": "5.199", "description": "Версия API"},
        ],
    },
    "config": {
        "environments": [
            {
                "name": "api.vk.ru",
                "color": "#0077FF",
                "variables": [
                    {"name": "baseUrl", "value": "https://api.vk.ru"},
                    {"name": "apiVersion", "value": "5.199"},
                    {"secret": True, "name": "accessToken", "type": "string", "description": "Токен пользователя"},
                    {"secret": True, "name": "groupToken", "type": "string", "description": "Токен сообщества"},
                ],
            }
        ]
    },
    "extensions": {"bruno": {"presets": {"request": {"type": "http", "url": "{{baseUrl}}/method"}}}},
    "items": [
        {
            "info": {"name": "Users", "type": "folder", "seq": 2},
            "request": {"auth": "inherit"},
            "docs": "# Users\n\n1 метод(ов) VK API.",
            "items": [
                {
                    "info": {
                        "name": "users.get",
                        "type": "http",
                        "seq": 1,
                        "description": "Возвращает подробную информацию о пользователях.",
                    },
                    "http": {
                        "method": "POST",
                        "url": "{{baseUrl}}/method/users.get",
                        "auth": "inherit",
                        "body": {
                            "type": "form-urlencoded",
                            "data": [
                                {"name": "user_ids", "value": "", "description": "ID пользователей"},
                                {"name": "fields", "value": "bdate", "disabled": True},
                                {"name": "v", "value": "{{apiVersion}}"},
                            ],
                        },
                    },
                    "docs": "# users.get\n\n## Параметры\n\n| Параметр |\n|---|",
                }
            ],
        }
    ],
    "docs": "# VK API\n\nКоллекция методов VK API.",
}


def first_folder(doc):
    return doc["item"][0]


def first_request(doc):
    return doc["item"][0]["item"][0]


class TestToPostman(unittest.TestCase):
    def test_root_info_schema_name_description(self):
        doc = g.to_postman(COLLECTION)
        self.assertEqual(doc["info"]["schema"], POSTMAN_SCHEMA_URL)
        self.assertEqual(doc["info"]["name"], "VK API")
        self.assertEqual(doc["info"]["description"], "# VK API\n\nКоллекция методов VK API.")

    def test_postman_id_is_stable_uuid(self):
        id1 = g.to_postman(COLLECTION)["info"]["_postman_id"]
        uuid.UUID(id1)
        id2 = g.to_postman(COLLECTION)["info"]["_postman_id"]
        self.assertEqual(id1, id2)
        other = json.loads(json.dumps(COLLECTION))
        other["info"]["version"] = "5.200 (2026-09-16)"
        self.assertNotEqual(id1, g.to_postman(other)["info"]["_postman_id"])

    def test_collection_auth_bearer(self):
        doc = g.to_postman(COLLECTION)
        self.assertEqual(
            doc["auth"],
            {"type": "bearer", "bearer": [{"key": "token", "value": "{{accessToken}}", "type": "string"}]},
        )

    def test_test_event_uses_pm_api(self):
        script = g.to_postman(COLLECTION)["event"][0]
        self.assertEqual(script["listen"], "test")
        self.assertEqual(script["script"]["type"], "text/javascript")
        self.assertIsInstance(script["script"]["exec"], list)
        code = "\n".join(script["script"]["exec"])
        self.assertIn("pm.response.json()", code)
        self.assertIn("pm.test(", code)
        self.assertIn("error_code", code)

    def test_variables(self):
        variables = {v["key"]: v for v in g.to_postman(COLLECTION)["variable"]}
        self.assertEqual(variables["baseUrl"]["value"], "https://api.vk.ru")
        self.assertEqual(variables["apiVersion"]["value"], "5.199")
        self.assertEqual(variables["accessToken"]["value"], "")

    def test_folder_mapping(self):
        folder = first_folder(g.to_postman(COLLECTION))
        self.assertEqual(folder["name"], "Users")
        self.assertEqual(folder["description"], "# Users\n\n1 метод(ов) VK API.")
        self.assertEqual(len(folder["item"]), 1)

    def test_request_mapping(self):
        req = first_request(g.to_postman(COLLECTION))
        self.assertEqual(req["name"], "users.get")
        http = req["request"]
        self.assertEqual(http["method"], "POST")
        self.assertEqual(http["url"], "{{baseUrl}}/method/users.get")
        self.assertNotIn("auth", http)
        self.assertEqual(http["body"]["mode"], "urlencoded")
        rows = http["body"]["urlencoded"]
        self.assertEqual(
            rows[0],
            {"key": "user_ids", "value": "", "type": "text", "description": "ID пользователей"},
        )
        self.assertEqual(rows[1], {"key": "fields", "value": "bdate", "type": "text", "disabled": True})
        self.assertEqual(rows[2], {"key": "v", "value": "{{apiVersion}}", "type": "text"})

    def test_request_description_is_full_docs(self):
        req = first_request(g.to_postman(COLLECTION))
        self.assertEqual(req["request"]["description"], "# users.get\n\n## Параметры\n\n| Параметр |\n|---|")

    def test_extensions_not_leaked(self):
        doc = g.to_postman(COLLECTION)
        self.assertNotIn("extensions", doc)
        self.assertNotIn("opencollection", doc)

    def test_environment_file(self):
        env = g.to_postman_environment(COLLECTION["config"]["environments"][0])
        self.assertEqual(env["name"], "api.vk.ru")
        self.assertEqual(env["_postman_variable_scope"], "environment")
        values = {v["key"]: v for v in env["values"]}
        self.assertEqual(values["baseUrl"]["value"], "https://api.vk.ru")
        self.assertEqual(values["accessToken"]["value"], "")
        self.assertTrue(values["accessToken"]["enabled"])
        self.assertNotIn("description", values["accessToken"])

    def test_dump_postman_json(self):
        text = g.dump_postman(COLLECTION)
        doc = json.loads(text)
        self.assertEqual(doc["info"]["name"], "VK API")


class TestDefaultOutPath(unittest.TestCase):
    def test_tree(self):
        self.assertEqual(g.default_out_path("tree"), pathlib.Path("dist/opencollection/vk-api"))

    def test_bundled(self):
        self.assertEqual(g.default_out_path("bundled"), pathlib.Path("dist/opencollection/vk-api.yaml"))

    def test_postman(self):
        out = g.default_out_path("postman")
        self.assertEqual(out, pathlib.Path("dist/postman/vk-api.postman_collection.json"))
        self.assertEqual(
            g.postman_environment_path(out),
            pathlib.Path("dist/postman/vk-api.postman_environment.json"),
        )


if __name__ == "__main__":
    unittest.main()
