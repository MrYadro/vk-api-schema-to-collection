import json
import pathlib
import re

from formats import FormatSpec, build_collection

VAR_PATTERN = re.compile(r"\{\{\s*([^{}\s][^{}]*?)\s*\}\}")

VK_ERROR_HINTS = "{5: 'невалидный или истёкший токен', 6: 'слишком много запросов в секунду', 7: 'нет права доступа (scope)', 15: 'доступ к методу запрещён', 18: 'страница не найдена или удалена', 27: 'нет прав на это сообщество', 29: 'достигнут дневной лимит метода', 100: 'неверный параметр', 113: 'неверное значение параметра', 1200: 'приложение в тестовом режиме'}"

INSOMNIA_TEST_SCRIPT = f"""const body = insomnia.response.json();
if (body && typeof body === 'object' && body.error) {{
  const hints = {VK_ERROR_HINTS};
  const e = body.error;
  const hint = hints[e.error_code] ? ` — ${{hints[e.error_code]}}` : '';
  insomnia.test(`VK error ${{e.error_code}}${{hint}}: ${{e.error_msg}}`, () => {{
    throw new Error(`VK API вернул ошибку ${{e.error_code}}: ${{e.error_msg}}${{hint}}`);
  }});
}} else {{
  insomnia.test('VK API: без ошибок', () => {{
    insomnia.expect(body && body.error).to.not.exist;
  }});
}}"""


def _var(value):
    return VAR_PATTERN.sub(r"{{ \1 }}", value)


def _params(rows):
    out = []
    for i, r in enumerate(rows):
        param = {"id": f"__P_{i}__", "name": r["name"], "value": _var(r.get("value", ""))}
        if r.get("description"):
            param["description"] = r["description"]
        if r.get("disabled"):
            param["disabled"] = True
        out.append(param)
    return out


def to_insomnia(collection):
    resources = [
        {"_id": "__WORKSPACE_ID__", "_type": "workspace", "name": collection["info"]["name"], "scope": "collection"},
    ]
    for env in collection.get("config", {}).get("environments", []):
        data = {v["name"]: v.get("value", "") for v in env.get("variables", [])}
        kv = [
            {"id": f"__KVP_{i}__", "name": v["name"], "value": v.get("value", ""), "type": "secret" if v.get("secret") else "str", "enabled": True}
            for i, v in enumerate(env.get("variables", []))
        ]
        resources.append(
            {
                "_id": "__ENV_1__",
                "_type": "environment",
                "parentId": "__BASE_ENVIRONMENT_ID__",
                "name": env["name"],
                "color": env.get("color", "#0077FF"),
                "data": data,
                "dataPropertyOrder": {"&": [v["name"] for v in env.get("variables", [])]},
                "kvPairData": kv,
            }
        )
    resources.append(
        {
            "_id": "__GRP_0__",
            "_type": "request_group",
            "parentId": "__WORKSPACE_ID__",
            "name": collection["info"]["name"],
            "description": collection.get("docs") or "",
            "metaSortKey": 0,
            "afterResponseScript": INSOMNIA_TEST_SCRIPT,
            "authentication": {"type": "bearer", "token": _var(collection["request"]["auth"]["token"]), "prefix": ""},
        }
    )
    for i, folder in enumerate(collection.get("items", []), start=1):
        resources.append(
            {
                "_id": f"__GRP_{i}__",
                "_type": "request_group",
                "parentId": "__GRP_0__",
                "name": folder["info"]["name"],
                "description": folder.get("docs") or folder["info"].get("description") or "",
                "metaSortKey": i * 1000,
            }
        )
        for j, req in enumerate(folder.get("items", []), start=1):
            http = req["http"]
            resources.append(
                {
                    "_id": f"__REQ_{i}_{j}__",
                    "_type": "request",
                    "parentId": f"__GRP_{i}__",
                    "name": req["info"]["name"],
                    "method": http["method"],
                    "url": _var(http["url"]),
                    "body": {"mimeType": "application/x-www-form-urlencoded", "params": _params(http.get("body", {}).get("data", []))},
                    "description": req.get("docs") or req["info"].get("description") or "",
                    "metaSortKey": j * 1000,
                }
            )
    return {"_type": "export", "__export_format": 4, "resources": resources}


def write_insomnia(collection, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(to_insomnia(collection), ensure_ascii=False, indent=2), encoding="utf-8")
    return 1, ""


def matches(path):
    name = pathlib.Path(path).name
    return "insomnia" in name and name.endswith(".json")


def validate(path, schema_override=None):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if doc.get("_type") != "export" or doc.get("__export_format") != 4:
        raise ValueError(f"not an insomnia v4 export: {path}")
    types = [r["_type"] for r in doc.get("resources", [])]
    return types.count("request_group") - 1, types.count("request")


INSOMNIA_SPEC = FormatSpec(
    name="insomnia",
    default_out="dist/insomnia/vk-api.insomnia.json",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_insomnia,
    matches=matches,
    validate=validate,
)
