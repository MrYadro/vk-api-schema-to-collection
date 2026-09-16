import json
import pathlib
import tempfile
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
        self.assertEqual(variables["accessToken"]["type"], "secret")
        self.assertNotIn("type", variables["baseUrl"])

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
        self.assertIsInstance(env["color"], int)
        values = {v["key"]: v for v in env["values"]}
        self.assertEqual(values["baseUrl"]["value"], "https://api.vk.ru")
        self.assertEqual(values["accessToken"]["value"], "")
        self.assertTrue(values["accessToken"]["enabled"])
        self.assertNotIn("description", values["accessToken"])
        self.assertEqual(values["accessToken"]["type"], "secret")
        self.assertEqual(values["groupToken"]["type"], "secret")
        self.assertNotIn("type", values["baseUrl"])

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


MINI_SCHEMA = {
    "users/methods.json": {
        "methods": [
            {
                "name": "users.get",
                "description": "Returns users.",
                "parameters": [
                    {
                        "name": "user_ids",
                        "description": "User IDs.",
                        "type": "array",
                        "items": {"$ref": "objects.json#/definitions/user_id"},
                        "maxItems": 1000,
                        "required": True,
                        "entity": "profiles",
                    },
                    {"name": "name_case", "type": "string", "$ref": "objects.json#/definitions/name_case"},
                    {"name": "secret", "type": "string", "description": "hidden param"},
                ],
                "responses": {"response": {"$ref": "responses.json#/definitions/users_get_response"}},
            },
            {"name": "users.secretMethod", "description": "Hidden.", "nodoc": True},
        ]
    },
    "users/objects.json": {
        "definitions": {
            "user_id": {"type": ["integer", "string"]},
            "name_case": {"enum": ["nom", "gen"], "nodocEnum": ["gen"]},
        }
    },
    "users/responses.json": {
        "definitions": {
            "users_get_response": {
                "type": "object",
                "properties": {"response": {"type": "array", "items": {"$ref": "objects.json#/definitions/user_id"}}},
            }
        }
    },
    "wall/methods.json": {
        "methods": [
            {
                "name": "wall.post",
                "description": "Creates a post on the wall.",
                "parameters": [{"name": "message", "type": "string", "required": True}],
            }
        ]
    },
}

MINI_DESCRIPTIONS = {
    "users.get": {"description": "Возвращает пользователей.", "params": {"user_ids": "ID пользователей."}}
}


class TestBuildOpenapi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.tmp.name)
        for rel, doc in MINI_SCHEMA.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc), encoding="utf-8")
        cls.desc_path = root / "descriptions.json"
        cls.desc_path.write_text(json.dumps(MINI_DESCRIPTIONS), encoding="utf-8")
        cls.doc, cls.stats = g.build_openapi(root, "5.199", "VK API", cls.desc_path, False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_root(self):
        self.assertEqual(self.doc["openapi"], "3.1.0")
        self.assertEqual(self.doc["info"]["title"], "VK API")
        self.assertEqual(self.doc["info"]["version"], "5.199")
        self.assertEqual(self.doc["servers"][0]["url"], "https://api.vk.ru")
        self.assertEqual(self.doc["security"], [{"bearerAuth": []}])
        self.assertEqual(
            self.doc["components"]["securitySchemes"]["bearerAuth"],
            {"type": "http", "scheme": "bearer", "bearerFormat": "access_token"},
        )
        self.assertIn("VK API", self.doc["info"]["description"])

    def test_tags_are_sorted_categories(self):
        self.assertEqual([t["name"] for t in self.doc["tags"]], ["Users", "Wall"])

    def test_private_methods_excluded(self):
        self.assertNotIn("/method/users.secretMethod", self.doc["paths"])
        self.assertEqual(set(self.doc["paths"]), {"/method/users.get", "/method/wall.post"})

    def test_operation_fields(self):
        op = self.doc["paths"]["/method/users.get"]["post"]
        self.assertEqual(op["operationId"], "users.get")
        self.assertEqual(op["tags"], ["Users"])
        self.assertEqual(op["summary"], "Возвращает пользователей.")
        self.assertEqual(op["description"], "Возвращает пользователей.")
        self.assertEqual(op["security"], [{"bearerAuth": []}])
        self.assertIn("requestBody", op)
        self.assertIn("200", op["responses"])

    def test_request_body_schema(self):
        op = self.doc["paths"]["/method/users.get"]["post"]
        schema = op["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]
        self.assertEqual(
            schema["properties"]["user_ids"],
            {
                "type": "array",
                "description": "ID пользователей.",
                "items": {"$ref": "#/components/schemas/users.user_id"},
                "maxItems": 1000,
            },
        )
        name_case = schema["properties"]["name_case"]
        self.assertEqual(name_case["type"], "string")
        self.assertEqual(name_case["$ref"], "#/components/schemas/users.name_case")
        self.assertIn("v", schema["properties"])
        self.assertEqual(schema["properties"]["v"]["default"], "5.199")
        self.assertEqual(schema["required"], ["user_ids", "v"])

    def test_components_with_namespaced_refs(self):
        schemas = self.doc["components"]["schemas"]
        self.assertEqual(schemas["users.user_id"], {"type": ["integer", "string"]})
        self.assertEqual(schemas["users.name_case"], {"enum": ["nom"]})
        response = schemas["users.users_get_response"]
        self.assertEqual(
            response["properties"]["response"]["items"],
            {"$ref": "#/components/schemas/users.user_id"},
        )

    def test_vk_error_component(self):
        error = self.doc["components"]["schemas"]["VkError"]
        self.assertEqual(error["properties"]["error"]["required"], ["error_code", "error_msg"])
        resp = self.doc["paths"]["/method/users.get"]["post"]["responses"]["200"]
        refs = [s["$ref"] for s in resp["content"]["application/json"]["schema"]["oneOf"]]
        self.assertIn("#/components/schemas/users.users_get_response", refs)
        self.assertIn("#/components/schemas/VkError", refs)

    def test_method_without_responses(self):
        op = self.doc["paths"]["/method/wall.post"]["post"]
        self.assertIn("200", op["responses"])
        self.assertEqual(op["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]["required"], ["message", "v"])

    def test_no_vk_vendor_keys_in_schemas(self):
        dumped = json.dumps(self.doc)
        self.assertNotIn("nodocEnum", dumped)
        self.assertNotIn('"entity"', dumped)

    def test_stats(self):
        self.assertEqual(self.stats["operations"], 2)
        self.assertEqual(self.stats["schemas"] >= 4, True)


    def test_openapi(self):
        self.assertEqual(g.default_out_path("openapi"), pathlib.Path("dist/openapi/vk-api.yaml"))


class TestYamlEmit(unittest.TestCase):
    def test_numeric_keys_quoted(self):
        out = g.to_yaml({"200": "ok"})
        self.assertIn('"200":', out)
        self.assertIn("ok", out)

    def test_numeric_string_values_quoted(self):
        out = g.to_yaml({"code": "200"})
        self.assertIn('"200"', out)


    def test_multiline_string_block_scalar(self):
        out = g.to_yaml({"description": "line1\nline2"})
        self.assertIn("description: |-\n", out)
        self.assertIn("  line1\n", out)
        self.assertIn("  line2\n", out)

    def test_multiline_leading_space_falls_back_to_quoted(self):
        out = g.to_yaml({"description": " first line\nsecond"})
        self.assertIn('description: " first line\\nsecond"', out)

    def test_singleline_string_stays_quoted(self):
        out = g.to_yaml({"a": "simple"})
        self.assertIn("a: simple", out)


class TestToPostmanV3(unittest.TestCase):
    def test_collection_definition(self):
        doc = g.postman_v3_definition(COLLECTION)
        self.assertEqual(doc["$kind"], "collection")
        self.assertEqual(doc["description"], "# VK API\n\nКоллекция методов VK API.")
        self.assertEqual(doc["variables"], {"baseUrl": "https://api.vk.ru", "apiVersion": "5.199", "accessToken": ""})
        script = doc["scripts"][0]
        self.assertEqual(script["type"], "http:afterResponse")
        self.assertEqual(script["language"], "text/javascript")
        self.assertIn("pm.response.json()", script["code"])
        auth = doc["auth"][0]
        self.assertEqual(auth["type"], "bearer")
        self.assertEqual(auth["credentials"], {"token": "{{accessToken}}"})
        uuid.UUID(auth["id"])

    def test_folder_definition(self):
        folder = COLLECTION["items"][0]
        doc = g.postman_v3_folder_definition(folder)
        self.assertEqual(doc["$kind"], "collection")
        self.assertEqual(doc["description"], "# Users\n\n1 метод(ов) VK API.")
        self.assertEqual(doc["order"], 2000)

    def test_request(self):
        req = COLLECTION["items"][0]["items"][0]
        doc = g.postman_v3_request(req)
        self.assertEqual(doc["$kind"], "http-request")
        self.assertEqual(doc["url"], "{{baseUrl}}/method/users.get")
        self.assertEqual(doc["method"], "POST")
        self.assertEqual(doc["description"], "# users.get\n\n## Параметры\n\n| Параметр |\n|---|")
        self.assertEqual(doc["order"], 1000)
        rows = doc["body"]["content"]
        self.assertEqual(doc["body"]["type"], "urlencoded")
        self.assertEqual(rows[0], {"key": "user_ids", "value": "", "description": "ID пользователей"})
        self.assertEqual(rows[1], {"key": "fields", "value": "bdate", "disabled": True})
        self.assertEqual(rows[-1], {"key": "v", "value": "{{apiVersion}}"})

    def test_environment(self):
        doc = g.postman_v3_environment(COLLECTION["config"]["environments"][0])
        self.assertEqual(doc["name"], "api.vk.ru")
        self.assertEqual(doc["color"], g.POSTMAN_ENVIRONMENT_COLOR)
        self.assertEqual(doc["values"][0], {"key": "baseUrl", "value": "https://api.vk.ru"})
        self.assertEqual(
            doc["values"][2],
            {"key": "accessToken", "value": "", "description": "Токен пользователя"},
        )


class TestWritePostmanV3(unittest.TestCase):
    def test_writes_tree(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            files = g.write_postman_v3(COLLECTION, out)
            root = out / "postman"
            self.assertTrue((root / "collections/VK API/.resources/definition.yaml").is_file())
            self.assertTrue((root / "collections/VK API/Users/.resources/definition.yaml").is_file())
            self.assertTrue((root / "collections/VK API/Users/users.get.request.yaml").is_file())
            self.assertTrue((root / "environments/api.vk.ru.environment.yaml").is_file())
            req_text = (root / "collections/VK API/Users/users.get.request.yaml").read_text(encoding="utf-8")
            self.assertIn("$kind: http-request", req_text)
            self.assertIn("order: 1000", req_text)
            self.assertEqual(files, 4)

    def test_default_out(self):
        self.assertEqual(g.default_out_path("postman-v3"), pathlib.Path("dist/postman/vk-api-local"))


if __name__ == "__main__":
    unittest.main()
