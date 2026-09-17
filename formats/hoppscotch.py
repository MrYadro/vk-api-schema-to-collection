import json
import pathlib

from formats import FormatSpec, build_collection

INHERIT = {"authType": "inherit", "authActive": True}
CONTENT_TYPES = {"form-urlencoded": "application/x-www-form-urlencoded"}

VK_ERROR_HINTS = "{5: 'невалидный или истёкший токен', 6: 'слишком много запросов в секунду', 7: 'нет права доступа (scope)', 15: 'доступ к методу запрещён', 18: 'страница не найдена или удалена', 27: 'нет прав на это сообщество', 29: 'достигнут дневной лимит метода', 100: 'неверный параметр', 113: 'неверное значение параметра', 1200: 'приложение в тестовом режиме'}"

HOPPSCOTCH_TEST_SCRIPT = f"""const body = pw.response.body;
if (body && typeof body === 'object' && body.error) {{
  const hints = {VK_ERROR_HINTS};
  const e = body.error;
  const hint = hints[e.error_code] ? ` — ${{hints[e.error_code]}}` : '';
  pw.test(`VK error ${{e.error_code}}${{hint}}: ${{e.error_msg}}`, () => {{
    throw new Error(`VK API вернул ошибку ${{e.error_code}}: ${{e.error_msg}}${{hint}}`);
  }});
}} else {{
  pw.test('VK API: без ошибок', () => {{
    pw.expect(body && body.error).toBe(undefined);
  }});
}}"""


def _var(value):
    return value.replace("{{", "<<").replace("}}", ">>")


def _body_string(rows):
    return "\n".join(f"{r['name']}: {_var(r.get('value', ''))}" for r in rows)


def hoppscotch_request(req):
    info = req["info"]
    body = req.get("http", {}).get("body", {})
    return {
        "v": "17",
        "name": info["name"],
        "method": req["http"]["method"],
        "endpoint": _var(req["http"]["url"]),
        "params": [],
        "headers": [],
        "auth": INHERIT,
        "body": {"contentType": CONTENT_TYPES.get(body.get("type"), body.get("type")), "body": _body_string(body.get("data", []))},
        "requestVariables": [],
        "responses": {},
        "preRequestScript": "",
        "testScript": HOPPSCOTCH_TEST_SCRIPT,
        "description": req.get("docs") or info.get("description") or "",
    }


def hoppscotch_folder(folder):
    return {
        "v": 12,
        "name": folder["info"]["name"],
        "folders": [],
        "requests": [hoppscotch_request(r) for r in folder.get("items", [])],
        "auth": INHERIT,
        "headers": [],
        "variables": [],
        "description": folder.get("docs") or folder["info"].get("description") or "",
        "preRequestScript": "",
        "testScript": "",
    }


def to_hoppscotch(collection):
    auth = collection["request"]["auth"]
    return {
        "v": 12,
        "name": collection["info"]["name"],
        "folders": [hoppscotch_folder(f) for f in collection.get("items", [])],
        "requests": [],
        "auth": {"authType": "bearer", "authActive": True, "token": _var(auth["token"])},
        "headers": [],
        "variables": [],
        "description": collection.get("docs") or "",
        "preRequestScript": "",
        "testScript": "",
    }


def to_hoppscotch_environments(collection):
    out = []
    for env in collection.get("config", {}).get("environments", []):
        variables = [
            {"key": v["name"], "initialValue": v.get("value", ""), "currentValue": v.get("value", ""), "secret": bool(v.get("secret"))}
            for v in env.get("variables", [])
        ]
        out.append({"v": 2, "id": env["name"], "name": env["name"], "variables": variables})
    return out


def write_hoppscotch(collection, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / "vk-api.hoppscotch.json").write_text(json.dumps(to_hoppscotch(collection), ensure_ascii=False, indent=2), encoding="utf-8")
    envs = to_hoppscotch_environments(collection)
    for env in envs:
        (out / f"{env['name']}.hoppscotch.env.json").write_text(json.dumps([env], ensure_ascii=False, indent=2), encoding="utf-8")
    note = f" +{len(envs)} environment file(s)" if envs else ""
    return 1 + len(envs), note


def matches(path):
    return ".hoppscotch." in pathlib.Path(path).name and pathlib.Path(path).name.endswith(".json")


def validate(path, schema_override=None):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, list):
        doc = doc[0]
    if doc.get("v") == 2:
        return 0, len(doc.get("variables", []))
    folders = doc.get("folders", [])
    requests = sum(len(f.get("requests", [])) for f in folders) + len(doc.get("requests", []))
    return len(folders), requests


HOPPSCOTCH_SPEC = FormatSpec(
    name="hoppscotch",
    default_out="dist/hoppscotch",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_hoppscotch,
    matches=matches,
    validate=validate,
)
