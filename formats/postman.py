import json
import pathlib
import uuid

import core
from core import SAFE_FILENAME, jsonschema_validator, load_document
from formats import FormatSpec, build_collection

POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
POSTMAN_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/MrYadro/vk-api-schema-to-collection")

POSTMAN_TEST_SCRIPT = """let body = null;
try { body = pm.response.json(); } catch (err) {}
if (body && typeof body === 'object' && body.error) {
  const hints = {5: 'невалидный или истёкший токен', 6: 'слишком много запросов в секунду', 7: 'нет права доступа (scope)', 15: 'доступ к методу запрещён', 18: 'страница не найдена или удалена', 27: 'нет прав на это сообщество', 29: 'достигнут дневной лимит метода', 100: 'неверный параметр', 113: 'неверное значение параметра', 1200: 'приложение в тестовом режиме'};
  const e = body.error;
  const hint = hints[e.error_code] ? ` — ${hints[e.error_code]}` : '';
  pm.test(`VK error ${e.error_code}${hint}: ${e.error_msg}`, () => {
    throw new Error(`VK API вернул ошибку ${e.error_code}: ${e.error_msg}${hint}`);
  });
} else {
  pm.test('VK API: без ошибок', () => {
    pm.expect(body && body.error).to.not.exist;
  });
}"""


def postman_id(info):
    return str(uuid.uuid5(POSTMAN_NAMESPACE, f"{info.get('name', '')}/{info.get('version', '')}"))


def postman_param(row):
    out = {"key": row["name"], "value": row.get("value", ""), "type": "text"}
    if row.get("disabled"):
        out["disabled"] = True
    if row.get("description"):
        out["description"] = row["description"]
    return out


def postman_request(req):
    info = req["info"]
    http = req["http"]
    request = {"method": http["method"], "url": http["url"]}
    description = req.get("docs") or info.get("description")
    if description:
        request["description"] = description
    if http.get("body"):
        request["body"] = {"mode": "urlencoded", "urlencoded": [postman_param(r) for r in http["body"].get("data", [])]}
    return {"name": info["name"], "request": request}


def postman_folder(folder):
    info = folder["info"]
    out = {"name": info["name"]}
    description = folder.get("docs") or info.get("description")
    if description:
        out["description"] = description
    out["item"] = [
        postman_request(item) if item["info"]["type"] == "http" else postman_folder(item) for item in folder["items"]
    ]
    return out


def to_postman(collection):
    info = collection["info"]
    variables = []
    for var in collection["request"].get("variables", []):
        entry = {"key": var["name"], "value": var.get("value", "")}
        if var.get("description"):
            entry["description"] = var["description"]
        variables.append(entry)
    token = {}
    for env in collection.get("config", {}).get("environments", []):
        for var in env.get("variables", []):
            if var.get("name") == "accessToken":
                token = var
                break
    token_entry = {"key": "accessToken", "value": "", "type": "secret"}
    if token.get("description"):
        token_entry["description"] = token["description"]
    variables.append(token_entry)
    auth = collection["request"]["auth"]
    return {
        "info": {
            "_postman_id": postman_id(info),
            "name": info.get("name", "collection"),
            "schema": POSTMAN_SCHEMA_URL,
            "description": collection.get("docs"),
        },
        "auth": {"type": auth["type"], auth["type"]: [{"key": "token", "value": auth["token"], "type": "string"}]},
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": POSTMAN_TEST_SCRIPT.splitlines()}}],
        "variable": variables,
        "item": [postman_folder(folder) for folder in collection["items"]],
    }


POSTMAN_ENVIRONMENT_COLOR = 212  # hue-колесо Postman 0-360; 212 = #0077FF (VK blue)


def to_postman_environment(env):
    return {
        "name": env["name"],
        "values": [
            {"key": var["name"], "value": var.get("value", ""), "enabled": True, **({"type": "secret"} if var.get("secret") else {})}
            for var in env.get("variables", [])
        ],
        "color": POSTMAN_ENVIRONMENT_COLOR,
        "_postman_variable_scope": "environment",
    }


def dump_postman(collection):
    return json.dumps(to_postman(collection), ensure_ascii=False, indent=2) + "\n"


def dump_postman_environment(env):
    return json.dumps(to_postman_environment(env), ensure_ascii=False, indent=2) + "\n"


def postman_environment_path(out_path):
    name = out_path.name.replace("postman_collection", "postman_environment")
    if name == out_path.name:
        name = f"{out_path.stem}.postman_environment{out_path.suffix}"
    return out_path.parent / name


def write_postman(collection, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_postman(collection), encoding="utf-8")
    env_paths = []
    for i, env in enumerate(collection.get("config", {}).get("environments", [])):
        if i == 0:
            env_path = postman_environment_path(out)
        else:
            env_path = out.parent / f"{SAFE_FILENAME.sub('_', env['name'])}.postman_environment.json"
        env_path.write_text(dump_postman_environment(env), encoding="utf-8")
        env_paths.append(env_path)
    note = f" +{len(env_paths)} environment file(s)" if env_paths else ""
    return 1 + len(env_paths), note


def matches(path):
    name = pathlib.Path(path).name
    return name.endswith(".json") and ("postman_collection" in name or "postman_environment" in name)


def validate_postman_collection(doc_path, schema):
    doc = load_document(doc_path)
    jsonschema_validator(schema).validate(doc)
    folders = 0
    requests = 0

    def walk(items):
        nonlocal folders, requests
        for item in items:
            if "item" in item:
                folders += 1
                walk(item["item"])
            elif "request" in item:
                requests += 1

    walk(doc.get("item", []))
    return folders, requests


def validate_postman_environment(doc_path, schema):
    doc = load_document(doc_path)
    jsonschema_validator(schema).validate(doc)
    return 0, len(doc.get("values", []))


def validate(path, schema_override=None):
    name = pathlib.Path(path).name
    if "postman_environment" in name:
        try:
            schema = core.load_schema(None, core.POSTMAN_ENVIRONMENT_SCHEMA_URL)
        except OSError:
            print(f"SKIP: postman environment schema unavailable online ({core.POSTMAN_ENVIRONMENT_SCHEMA_URL}), validation skipped")
            return None
        _, values = validate_postman_environment(path, schema)
        return 0, values
    schema = core.allow_postman_secret_type(core.load_schema(None, core.POSTMAN_COLLECTION_SCHEMA_URL))
    return validate_postman_collection(path, schema)


POSTMAN_SPEC = FormatSpec(
    name="postman",
    default_out="dist/postman/vk-api.postman_collection.json",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_postman,
    matches=matches,
    validate=validate,
)
