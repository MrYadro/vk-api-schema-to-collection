import pathlib

import core
from core import (
    RefResolver,
    collect_methods,
    first_sentence,
    is_public,
    jsonschema_validator,
    load_descriptions,
    load_document,
    method_description,
    param_description,
    to_yaml,
    visible_enum,
)
from formats import FormatSpec

OPENAPI_SPEC_VERSION = "3.1.0"

OPENAPI_DESCRIPTION = """VK API methods generated from [vk-api-schema](https://github.com/VKCOM/vk-api-schema).

- Версия API: **__API_VERSION__** (передаётся параметром `v` в каждом запросе)
- Все методы — `POST` с телом `application/x-www-form-urlencoded`
- Параметры-массивы передаются значениями через запятую (`user_ids=1,2,3`)
- Схемы ответов собраны из `responses.json` схемы VK; ошибки VK приходят с HTTP 200 в теле (`VkError`)

## Аутентификация

`Authorization: Bearer {{accessToken}}` — пользовательский токен.
Для токенов сообщества/приложения/анонимного подставьте соответствующий ключ
(см. [dev.vk.ru → Ключи доступа](https://dev.vk.ru/ru/api/access-token/get-started)).

Документация методов: [dev.vk.ru](https://dev.vk.ru/ru)."""

VK_ERROR_SCHEMA = {
    "type": "object",
    "description": "Ошибка VK API: возвращается с HTTP 200 в теле ответа.",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "error_code": {"type": "integer", "description": "Код ошибки (см. https://dev.vk.ru/ru/reference/errors)"},
                "error_msg": {"type": "string", "description": "Текст ошибки"},
                "request_params": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                    },
                },
            },
            "required": ["error_code", "error_msg"],
        }
    },
    "required": ["error"],
}

OPENAPI_STRIP_KEYS = {"entity", "nodoc", "nodocEnum", "hidden", "meta"}


def register_component(ref, cur_file, resolver, components, sources):
    target, target_file = resolver.resolve(ref, cur_file)
    if not isinstance(target, dict):
        return None
    pointer = ref.partition("#")[2]
    parts = pointer.lstrip("/").split("/")
    if len(parts) < 2 or parts[0] != "definitions":
        return None
    name = parts[-1].replace("~1", "/").replace("~0", "~")
    ns = target_file.parent.name
    key = f"{ns}.{name}"
    if key in components:
        if sources.get(key) == (str(target_file), pointer):
            return f"#/components/schemas/{key}"
        key = f"{ns}.{target_file.stem}_{name}"
        if key in components:
            return f"#/components/schemas/{key}" if sources.get(key) == (str(target_file), pointer) else None
    components[key] = {}
    sources[key] = (str(target_file), pointer)
    components[key] = openapi_schema(target, target_file, resolver, components, sources)
    return f"#/components/schemas/{key}"


def openapi_schema(node, cur_file, resolver, components, sources):
    if isinstance(node, list):
        return [openapi_schema(item, cur_file, resolver, components, sources) for item in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k in OPENAPI_STRIP_KEYS:
            continue
        if k == "enum":
            out["enum"] = visible_enum(node)
        elif k == "$ref" and isinstance(v, str):
            ref = register_component(v, cur_file, resolver, components, sources)
            if ref is not None:
                out["$ref"] = ref
            else:
                target, target_file = resolver.resolve(v, cur_file)
                if isinstance(target, dict):
                    return openapi_schema(target, target_file, resolver, components, sources)
        elif isinstance(v, dict):
            out[k] = openapi_schema(v, cur_file, resolver, components, sources)
        elif isinstance(v, list):
            out[k] = openapi_schema(v, cur_file, resolver, components, sources)
        else:
            out[k] = v
    return out


def openapi_param_property(param, cur_file, resolver, components, sources, ru):
    node = {k: v for k, v in param.items() if k not in ("name", "description", "required")}
    prop = openapi_schema(node, cur_file, resolver, components, sources)
    desc = param_description(param, ru or {})
    if desc:
        prop["description"] = desc
    return prop


def openapi_responses(method, cur_file, resolver, components, sources):
    ok = {"type": "object", "description": "Успешный ответ."}
    resp_node = (method.get("responses") or {}).get("response")
    if isinstance(resp_node, dict):
        converted = openapi_schema(resp_node, cur_file, resolver, components, sources)
        if converted:
            ok = converted
    return {
        "200": {
            "description": "VK API отвечает HTTP 200 и для ошибок — тело либо успешный ответ, либо объект error (VkError).",
            "content": {"application/json": {"schema": {"oneOf": [ok, {"$ref": "#/components/schemas/VkError"}]}}},
        }
    }


def openapi_operation(method, cur_file, resolver, components, sources, ru, api_version, tag):
    name = method["name"]
    props = {}
    required = []
    for p in method.get("parameters") or []:
        prop_name = p.get("name", "")
        props[prop_name] = openapi_param_property(p, cur_file, resolver, components, sources, ru)
        if p.get("required") is True:
            required.append(prop_name)
    props["v"] = {"type": "string", "default": api_version, "description": "Версия API (передаётся в каждом запросе)."}
    required.append("v")
    desc = method_description(method, ru or {})
    op = {
        "tags": [tag],
        "summary": first_sentence(desc) or name,
        "operationId": name,
        "security": [{"bearerAuth": []}],
        "requestBody": {
            "required": True,
            "content": {"application/x-www-form-urlencoded": {"schema": {"type": "object", "properties": props, "required": required}}},
        },
        "responses": openapi_responses(method, cur_file, resolver, components, sources),
    }
    if desc:
        op["description"] = desc
    return op


def build_openapi(schema_dir, api_version, collection_name="VK API", descriptions_path=None, include_all=False):
    methods, collisions, encodings = collect_methods(schema_dir)
    if not include_all:
        methods = {name: entry for name, entry in methods.items() if is_public(entry[0])}
    resolver = RefResolver()
    ru_descriptions = load_descriptions(descriptions_path)
    components = {"VkError": VK_ERROR_SCHEMA}
    sources = {"VkError": ("builtin", "")}
    folders_map = {}
    for name in methods:
        folder = name.split(".", 1)[0] if "." in name else name
        folders_map.setdefault(folder, []).append(name)
    paths = {}
    tags = []
    for folder in sorted(folders_map):
        display_name = folder[0].upper() + folder[1:]
        tags.append({"name": display_name, "description": f"{len(folders_map[folder])} метод(ов) VK API."})
        for name in sorted(folders_map[folder]):
            method, cur_file = methods[name]
            ru = ru_descriptions.get(name)
            paths[f"/method/{name}"] = {
                "post": openapi_operation(method, cur_file, resolver, components, sources, ru, api_version, display_name)
            }
    doc = {
        "openapi": OPENAPI_SPEC_VERSION,
        "info": {
            "title": collection_name,
            "version": api_version,
            "description": OPENAPI_DESCRIPTION.replace("__API_VERSION__", api_version),
        },
        "servers": [{"url": "https://api.vk.ru"}],
        "tags": tags,
        "security": [{"bearerAuth": []}],
        "paths": paths,
        "components": {
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "access_token"}},
            "schemas": components,
        },
    }
    stats = {
        "operations": len(paths),
        "schemas": len(components),
        "collisions": collisions,
        "encodings": sorted(encodings),
        "ru_descriptions": len(ru_descriptions),
    }
    return doc, stats


def write_openapi(doc, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_yaml(doc), encoding="utf-8")
    return 1, ""


def matches(path):
    path = pathlib.Path(path)
    return path.name.endswith(".openapi.yaml") or path.parent.name == "openapi"


def validate_openapi(doc_path, schema):
    doc = load_document(doc_path)
    jsonschema_validator(schema).validate(doc)
    return len(doc.get("paths", {})), len(doc.get("components", {}).get("schemas", {}))


def validate(path, schema_override=None):
    schema = core.load_schema(schema_override, core.OPENAPI_SCHEMA_URL)
    return validate_openapi(path, schema)


OPENAPI_SPEC = FormatSpec(
    name="openapi",
    default_out="dist/openapi/vk-api.yaml",
    stats_keys=("operations", "schemas"),
    model_based=False,
    build=lambda ctx: build_openapi(ctx.schema_dir, ctx.api_version, ctx.name, ctx.descriptions, ctx.include_all),
    write=write_openapi,
    matches=matches,
    validate=validate,
)
