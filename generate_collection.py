#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request
import uuid

PLAIN_KEY = re.compile(r"[A-Za-z0-9_$-]+\Z")
PLAIN_SCALAR = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./()+,-]*\Z")
RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "~", ""}


def load_methods_file(path):
    raw = path.read_bytes()
    for enc in ("utf-8", "cp1251"):
        try:
            return json.loads(raw.decode(enc)), enc
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError(f"cannot decode {path}")


class RefResolver:
    def __init__(self):
        self.cache = {}

    def load(self, path):
        path = path.resolve()
        if path not in self.cache:
            self.cache[path] = load_methods_file(path)[0]
        return self.cache[path]

    def resolve(self, ref, cur_file):
        file_part, _, pointer = ref.partition("#")
        target_file = (cur_file.parent / file_part).resolve() if file_part else cur_file
        node = self.load(target_file)
        if pointer.startswith("/"):
            for part in pointer.lstrip("/").split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(node, dict) or part not in node:
                    return None, target_file
                node = node[part]
        return node, target_file


def collect_methods(schema_dir):
    methods = {}
    collisions = 0
    encodings = set()
    for methods_file in sorted(schema_dir.glob("*/methods.json")):
        data, enc = load_methods_file(methods_file)
        encodings.add(enc)
        for m in data.get("methods", []):
            name = m.get("name")
            if not name:
                continue
            if name in methods:
                collisions += 1
                continue
            methods[name] = (m, methods_file)
    return methods, collisions, encodings


def scalar(s):
    if PLAIN_SCALAR.fullmatch(s) and s.lower() not in RESERVED and not s[0].isdigit():
        return s
    return json.dumps(s, ensure_ascii=False)


def fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    return scalar(v)


def key(k):
    if PLAIN_KEY.fullmatch(k) and not k.isdigit() and k.lower() not in RESERVED:
        return k
    return json.dumps(k)


def block_scalar(v):
    return isinstance(v, str) and "\n" in v and all(not line.startswith((" ", "\t")) for line in v.split("\n"))


def emit(obj, indent, out):
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if block_scalar(v):
                out.append(f"{pad}{key(k)}: |-")
                out.extend(f"{pad}  {line}" for line in v.split("\n"))
            elif isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{key(k)}:")
                emit(v, indent + 1, out)
            elif isinstance(v, dict):
                out.append(f"{pad}{key(k)}: {{}}")
            elif isinstance(v, list):
                out.append(f"{pad}{key(k)}: []")
            else:
                out.append(f"{pad}{key(k)}: {fmt(v)}")
        return
    for item in obj:
        if not isinstance(item, dict):
            out.append(f"{pad}- {fmt(item)}")
            continue
        item_pad = pad + "  "
        first = True
        for k, v in item.items():
            prefix = f"{pad}- " if first else item_pad
            if block_scalar(v):
                out.append(f"{prefix}{key(k)}: |-")
                out.extend(f"{item_pad}  {line}" for line in v.split("\n"))
            elif isinstance(v, (dict, list)) and v:
                out.append(f"{prefix}{key(k)}:")
                emit(v, indent + 2, out)
            elif isinstance(v, dict):
                out.append(f"{prefix}{key(k)}: {{}}")
            elif isinstance(v, list):
                out.append(f"{prefix}{key(k)}: []")
            else:
                out.append(f"{prefix}{key(k)}: {fmt(v)}")
            first = False


def to_yaml(obj):
    out = []
    emit(obj, 0, out)
    return "\n".join(out) + "\n"


def visible_enum(node):
    if not isinstance(node, dict):
        return []
    hidden = set(node.get("nodocEnum") or [])
    return [v for v in (node.get("enum") or []) if v not in hidden]


def enum_walk(node, cur_file, resolver, visited, values, seen):
    if not isinstance(node, dict):
        return
    for v in visible_enum(node):
        s = str(v)
        if s not in seen:
            seen.add(s)
            values.append(s)
    one_of = node.get("oneOf")
    if isinstance(one_of, list):
        for branch in one_of:
            enum_walk(branch, cur_file, resolver, visited, values, seen)
    items = node.get("items")
    if isinstance(items, dict):
        enum_walk(items, cur_file, resolver, visited, values, seen)
    ref = node.get("$ref")
    if isinstance(ref, str):
        key = (str(cur_file), ref)
        if key in visited:
            return
        visited.add(key)
        target, target_file = resolver.resolve(ref, cur_file)
        if target is not None:
            enum_walk(target, target_file, resolver, visited, values, seen)


def param_enum_values(param, cur_file, resolver):
    values, seen = [], set()
    enum_walk(param, cur_file, resolver, set(), values, seen)
    return values


ANON_TOKEN_URL = "https://dev.vk.ru/getAnonymousToken"
LAST_VERSION_URL = "https://api.vk.ru/method/documentation.getLastVersion"


def get_latest_api_version(timeout=30):
    with urllib.request.urlopen(ANON_TOKEN_URL, timeout=timeout) as resp:
        token = json.loads(resp.read().decode("utf-8"))["response"]["token"]
    form = urllib.parse.urlencode({"v": "5.190", "access_token": token}).encode()
    req = urllib.request.Request(LAST_VERSION_URL, data=form, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["response"]


def resolve_api_version(value):
    if value == "latest":
        return get_latest_api_version()
    return value


BULLET_LINE = re.compile(r"^(\s*)\*\s+(.*)$")


def fix_bullets(text):
    if not text:
        return text
    lines = []
    for line in text.split("\n"):
        m = BULLET_LINE.match(line)
        if m:
            lines.append(f"{m.group(1)}- {m.group(2).replace(chr(96), '')}")
        else:
            lines.append(line)
    return "\n".join(lines)


def load_descriptions(path):
    if not path or not pathlib.Path(path).exists():
        return {}
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if isinstance(v, dict) and not v.get("missing")}


def param_description(param, ru):
    return fix_bullets(ru.get("params", {}).get(param.get("name", "")) or param.get("description"))


def method_description(method, ru):
    parts = []
    if ru:
        if ru.get("description"):
            parts.append(ru["description"])
        if ru.get("params_common_description"):
            parts.append(ru["params_common_description"])
    if not parts and method.get("description"):
        parts.append(method["description"])
    return fix_bullets("\n\n".join(parts))


def form_rows(param, cur_file, resolver, ru=None):
    name = param.get("name", "")
    desc = param_description(param, ru or {})
    enums = param_enum_values(param, cur_file, resolver)
    rows = []
    if enums:
        for v in enums:
            row = {"name": name, "value": v, "disabled": True}
            if desc and v == enums[0]:
                row["description"] = desc
            rows.append(row)
        return rows
    default = param.get("default")
    row = {"name": name, "value": "" if default is None else str(default)}
    if param.get("required") is not True:
        row["disabled"] = True
    if desc:
        row["description"] = desc
    rows.append(row)
    return rows


def md_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def method_docs(method, ru, cur_file=None, resolver=None):
    ru = ru or {}
    lines = [f"# {method['name']}", ""]
    desc = method_description(method, ru)
    if desc:
        lines += [desc, ""]
    token_types = method.get("access_token_type") or []
    if token_types:
        lines += ["Типы токенов: " + ", ".join(f"`{t}`" for t in token_types), ""]
    params = method.get("parameters") or []
    if params:
        lines += ["## Параметры", "", "| Параметр | Тип | Обяз. | Описание | Значения |", "|---|---|---|---|---|"]
        for p in params:
            name = p.get("name", "")
            if p.get("type"):
                ptype = p["type"]
            elif p.get("$ref"):
                ptype = "$" + str(p["$ref"]).rsplit("/", 1)[-1]
            else:
                ptype = "—"
            required = "да" if p.get("required") is True else "—"
            pdesc = fix_bullets(ru.get("params", {}).get(name) or p.get("description") or "")
            enum = param_enum_values(p, cur_file, resolver) if cur_file else []
            lines.append(f"| {md_cell(name)} | {md_cell(ptype)} | {required} | {md_cell(pdesc)} | {md_cell(', '.join(map(str, enum)))} |")
    else:
        lines += ["Метод не принимает параметров."]
    lines += ["", f"[Документация](https://dev.vk.ru/ru/method/{method['name']})"]
    return "\n".join(lines)


def build_request(method, cur_file, resolver, ru=None):
    name = method["name"]
    short = name
    data = []
    for p in method.get("parameters") or []:
        data.extend(form_rows(p, cur_file, resolver, ru))
    data.append({"name": "v", "value": "{{apiVersion}}"})
    info = {"name": short, "type": "http"}
    description = method_description(method, ru or {})
    if description:
        info["description"] = description
    return {
        "info": info,
        "http": {
            "method": "POST",
            "url": "{{baseUrl}}/method/" + name,
            "auth": "inherit",
            "body": {"type": "form-urlencoded", "data": data},
        },
        "docs": method_docs(method, ru, cur_file, resolver),
    }


TESTS_SCRIPT = """const body = res.getBody();
if (body && typeof body === 'object' && body.error) {
  const hints = {5: 'невалидный или истёкший токен', 6: 'слишком много запросов в секунду', 7: 'нет права доступа (scope)', 15: 'доступ к методу запрещён', 18: 'страница не найдена или удалена', 27: 'нет прав на это сообщество', 29: 'достигнут дневной лимит метода', 100: 'неверный параметр', 113: 'неверное значение параметра', 1200: 'приложение в тестовом режиме'};
  const e = body.error;
  const hint = hints[e.error_code] ? ` — ${hints[e.error_code]}` : '';
  test(`VK error ${e.error_code}${hint}: ${e.error_msg}`, () => {
    throw new Error(`VK API вернул ошибку ${e.error_code}: ${e.error_msg}${hint}`);
  });
} else {
  test('VK API: без ошибок', () => {
    expect(body && body.error).to.not.exist;
  });
}"""


DOCS_MD = """# VK API

Коллекция методов VK API, сгенерированная из публичной схемы [vk-api-schema](https://github.com/VKCOM/vk-api-schema).

- Версия API: **__API_VERSION__**
- Тело запросов: `form-urlencoded`, версия API передаётся параметром `v={{apiVersion}}`

## Быстрый старт

1. Выберите окружение **api.vk.ru** (по умолчанию уже выбрано).
2. Вставьте ключ доступа в секретную переменную `accessToken` (окружения → api.vk.ru).
3. Откройте `_Meta → Проверка токена (users.get)` и выполните — вернётся профиль владельца токена.

## Токены

| Переменная | Тип токена |
|---|---|
| `accessToken` | Пользовательский (используется коллекционным заголовком `Authorization: Bearer`) |
| `groupToken` | Ключ доступа сообщества |
| `serviceToken` | Сервисный ключ приложения |
| `anonymousToken` | Анонимный токен |

Чтобы работать от имени сообщества или приложения — подставьте соответствующий токен в `accessToken` (или переопределите auth на уровне запроса/папки).

Получить токен: [dev.vk.ru → Ключи доступа](https://dev.vk.ru/ru/api/access-token/get-started).

## Переменные

| Переменная | Значение |
|---|---|
| `baseUrl` | `https://api.vk.ru` (допустим `https://api.vk.com`) |
| `apiVersion` | Версия API в параметре `v` |

## Тесты

После каждого запроса автоматически проверяется ответ: если VK вернул `error`, тест падает с кодом и расшифровкой (`5` — токен истёк, `6` — rate limit, `100` — неверный параметр и т.д.).

## Параметры в запросах

Обязательные параметры включены, опциональные отключены (`disabled`) — включите нужные перед отправкой. Возможные значения enum идут отдельными выключенными строками.

## Полезное

- Папка `_Meta`: проверка токена и песочница `execute` (VKScript).
- Документация методов: [dev.vk.ru](https://dev.vk.ru/ru).
- Русские описания параметров подтянуты со страниц документации."""


def meta_request(name, method, description, data, seq):
    return {
        "info": {"name": name, "type": "http", "seq": seq, "description": description},
        "http": {
            "method": "POST",
            "url": "{{baseUrl}}/method/" + method,
            "auth": "inherit",
            "body": {"type": "form-urlencoded", "data": data},
        },
    }


def meta_folder(seq):
    items = [
        meta_request(
            "Проверка токена (users.get)",
            "users.get",
            "Возвращает профиль владельца текущего токена. Быстрая проверка, что переменная accessToken (или коллекционный Bearer) валидна.",
            [
                {"name": "fields", "value": "bdate,sex,city,contacts", "disabled": True, "description": "Дополнительные поля профиля"},
                {"name": "v", "value": "{{apiVersion}}"},
            ],
            1,
        ),
        meta_request(
            "execute (песочница)",
            "execute",
            "Универсальный метод: выполняет VKScript из параметра code и возвращает результат. Удобен для отладки составных запросов.",
            [
                {"name": "code", "value": "return [API.users.get()];", "description": "VKScript-код запроса"},
                {"name": "v", "value": "{{apiVersion}}"},
            ],
            2,
        ),
    ]
    return {
        "info": {"name": "_Meta", "type": "folder", "seq": seq, "description": "Служебные запросы: проверка токена и песочница execute."},
        "request": {"auth": "inherit"},
        "items": items,
    }


def build(schema_dir, api_version, collection_name="VK API", descriptions_path=None, include_all=False):
    methods, collisions, encodings = collect_methods(schema_dir)
    if not include_all:
        methods = {name: entry for name, entry in methods.items() if is_public(entry[0])}
    resolver = RefResolver()
    ru_descriptions = load_descriptions(descriptions_path)
    folders_map = {}
    for name in methods:
        folder = name.split(".", 1)[0] if "." in name else name
        folders_map.setdefault(folder, []).append(name)
    items = []
    seq = 1
    for folder in sorted(folders_map):
        seq += 1
        display_name = folder[0].upper() + folder[1:]
        requests = []
        folder_rows = ["| Метод | Описание |", "|---|---|"]
        for i, name in enumerate(sorted(folders_map[folder]), start=1):
            method, cur_file = methods[name]
            ru = ru_descriptions.get(name)
            req = build_request(method, cur_file, resolver, ru)
            req["info"]["seq"] = i
            requests.append(req)
            short = method_description(method, ru or {}).replace("\n", " ").strip()
            first = first_sentence(short)
            folder_rows.append(f"| [{name}](https://dev.vk.ru/ru/method/{name}) | {md_cell(first[:120])} |")
        items.append(
            {
                "info": {"name": display_name, "type": "folder", "seq": seq},
                "request": {"auth": "inherit"},
                "items": requests,
                "docs": f"# {display_name}\n\n{len(requests)} метод(ов) VK API.\n\n" + "\n".join(folder_rows),
            }
        )
    items.insert(0, meta_folder(1))
    today = datetime.date.today().isoformat()
    collection = {
        "opencollection": "1.0.0",
        "info": {
            "name": collection_name,
            "summary": "VK API methods generated from vk-api-schema",
            "version": f"{api_version} ({today})",
        },
        "request": {
            "auth": {"type": "bearer", "token": "{{accessToken}}"},
            "scripts": [{"type": "tests", "code": TESTS_SCRIPT}],
            "variables": [
                {"name": "baseUrl", "value": "https://api.vk.ru", "description": "Базовый URL API ВКонтакте (допустим также https://api.vk.com)."},
                {"name": "apiVersion", "value": api_version, "description": "Версия API — подставляется в параметр v каждого запроса."},
            ],
        },
        "extensions": {
            "bruno": {
                "presets": {
                    "request": {"type": "http", "url": "{{baseUrl}}/method"},
                    "defaultEnvironment": "api.vk.ru",
                }
            }
        },
        "config": {
            "environments": [
                {
                    "name": "api.vk.ru",
                    "color": "#0077FF",
                    "variables": [
                        {"name": "baseUrl", "value": "https://api.vk.ru", "description": "Базовый URL API ВКонтакте (допустим также https://api.vk.com)."},
                        {"name": "apiVersion", "value": api_version, "description": "Версия API — подставляется в параметр v каждого запроса."},
                        {"secret": True, "name": "accessToken", "type": "string", "description": "Токен пользователя (access_token_type: user). Используется коллекционным Bearer-заголовком."},
                        {"secret": True, "name": "groupToken", "type": "string", "description": "Токен сообщества (access_token_type: group)."},
                        {"secret": True, "name": "serviceToken", "type": "string", "description": "Сервисный токен приложения (access_token_type: service)."},
                        {"secret": True, "name": "anonymousToken", "type": "string", "description": "Анонимный токен (access_token_type: anonymous)."},
                    ] + ([{"secret": True, "name": "clientSecretToken", "type": "string", "description": "client_secret приложения (access_token_type: client_secret, только внутренние методы)."}] if include_all else []),
                }
            ]
        },
        "items": items,
        "docs": DOCS_MD.replace("__API_VERSION__", api_version),
    }
    stats = {
        "folders": len(items),
        "requests": sum(len(f["items"]) for f in items),
        "collisions": collisions,
        "encodings": sorted(encodings),
        "ru_descriptions": len(ru_descriptions),
    }
    return collection, stats


SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")
MULTI_UNDERSCORE = re.compile(r"_+")

_CYR = "абвгдежзийклмнопрстуфхцчшщъыьэюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
_LAT = "a b v g d e zh z i y k l m n o p r s t u f kh ts ch sh sch \" y ' e yu ya".split()
TRANSLIT = {ord(c): l for c, l in zip(_CYR, _LAT + [x.upper() for x in _LAT])}


def unique_filename(name, ext, used):
    base = MULTI_UNDERSCORE.sub("_", SAFE_FILENAME.sub("_", name.translate(TRANSLIT))).strip("._") or "unnamed"
    candidate = f"{base}{ext}"
    i = 2
    while candidate in used:
        candidate = f"{base}-{i}{ext}"
        i += 1
    used.add(candidate)
    return candidate


def write_tree(collection, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    root = {
        "opencollection": collection["opencollection"],
        "info": collection["info"],
        "request": collection["request"],
        "extensions": collection.get("extensions"),
        "docs": collection.get("docs"),
    }
    (out_dir / "opencollection.yml").write_text(to_yaml(root), encoding="utf-8")
    env_dir = out_dir / "environments"
    env_dir.mkdir(exist_ok=True)
    envs = collection.get("config", {}).get("environments", [])
    for env in envs:
        (env_dir / f"{SAFE_FILENAME.sub('_', env['name'])}.yml").write_text(to_yaml(env), encoding="utf-8")
    file_count = 1 + len(envs)
    for folder in collection["items"]:
        used = set()
        folder_dir = out_dir / SAFE_FILENAME.sub("_", folder["info"]["name"])
        folder_dir.mkdir(exist_ok=True)
        folder_doc = {k: v for k, v in folder.items() if k != "items"}
        (folder_dir / "folder.yml").write_text(to_yaml(folder_doc), encoding="utf-8")
        file_count += 1
        for req in folder["items"]:
            fname = unique_filename(req["info"]["name"], ".yml", used)
            (folder_dir / fname).write_text(to_yaml(req), encoding="utf-8")
            file_count += 1
    return file_count


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


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent


def default_schema_dir():
    root = os.environ.get("VK_API_SCHEMA_DIR")
    if not root:
        candidate = pathlib.Path.home() / "Dev/vk-api-schema"
        if candidate.is_dir():
            root = str(candidate)
    if not root:
        sys.exit("schema dir not found: clone https://github.com/VKCOM/vk-api-schema and set VK_API_SCHEMA_DIR or pass --schema-dir")
    for schema_dir in (pathlib.Path(root) / "api_schema", pathlib.Path(root)):
        if schema_dir.is_dir() and any(schema_dir.glob("*/methods.json")):
            return schema_dir
    sys.exit(f"schema dir not found under: {root}")


def is_public(method):
    return method.get("nodoc") is not True and (method.get("meta") or {}).get("hidden") is not True


def first_sentence(text):
    return re.split(r"(?<=[.!?])\s", text)[0] if text else ""


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


POSTMAN_V3_KIND_COLLECTION = "collection"
POSTMAN_V3_KIND_REQUEST = "http-request"


def postman_v3_auth_id(info):
    return str(uuid.uuid5(POSTMAN_NAMESPACE, f"v3-auth/{info.get('name', '')}/{info.get('version', '')}"))


def postman_v3_definition(collection):
    variables = {var["name"]: var.get("value", "") for var in collection["request"].get("variables", [])}
    variables["accessToken"] = ""
    auth = collection["request"]["auth"]
    return {
        "$kind": POSTMAN_V3_KIND_COLLECTION,
        "description": collection.get("docs"),
        "variables": variables,
        "scripts": [
            {
                "type": "http:afterResponse",
                "code": POSTMAN_TEST_SCRIPT,
                "language": "text/javascript",
            }
        ],
        "auth": [
            {
                "id": postman_v3_auth_id(collection["info"]),
                "type": auth["type"],
                "name": "bearer auth",
                "credentials": {"token": auth["token"]},
            }
        ],
    }


def postman_v3_folder_definition(folder):
    return {
        "$kind": POSTMAN_V3_KIND_COLLECTION,
        "description": folder.get("docs") or folder["info"].get("description"),
        "order": folder["info"].get("seq", 1) * 1000,
    }


def postman_v3_request(req):
    info = req["info"]
    http = req["http"]
    rows = []
    for row in http.get("body", {}).get("data", []):
        out = {"key": row["name"], "value": row.get("value", "")}
        if row.get("disabled"):
            out["disabled"] = True
        if row.get("description"):
            out["description"] = row["description"]
        rows.append(out)
    doc = {
        "$kind": POSTMAN_V3_KIND_REQUEST,
        "description": req.get("docs") or info.get("description"),
        "url": http["url"],
        "method": http["method"],
        "body": {"type": "urlencoded", "content": rows},
        "order": info.get("seq", 1) * 1000,
    }
    return doc


def postman_v3_environment(env):
    values = []
    for var in env.get("variables", []):
        out = {"key": var["name"], "value": var.get("value", "")}
        if var.get("description"):
            out["description"] = var["description"]
        values.append(out)
    return {
        "name": env["name"],
        "color": POSTMAN_ENVIRONMENT_COLOR,
        "values": values,
    }


POSTMAN_V3_UNSAFE_FILENAME = re.compile(r"[/\\:]")


def write_postman_v3(collection, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".postman").mkdir(parents=True, exist_ok=True)
    (out_dir / ".postman" / "resources.yaml").write_text(
        to_yaml({"workspace": {}, "cloudResources": {"collections": {}, "environments": {}, "globals": {}, "flows": {}, "documents": {}}}),
        encoding="utf-8",
    )
    root = out_dir / "postman"
    globals_dir = root / "globals"
    globals_dir.mkdir(parents=True, exist_ok=True)
    (globals_dir / "workspace.globals.yaml").write_text(
        to_yaml({"name": "Globals", "values": []}), encoding="utf-8"
    )
    coll_dir = root / "collections" / collection["info"]["name"]
    (coll_dir / ".resources").mkdir(parents=True, exist_ok=True)
    (coll_dir / ".resources" / "definition.yaml").write_text(
        to_yaml(postman_v3_definition(collection)), encoding="utf-8"
    )
    file_count = 3
    for folder in collection["items"]:
        folder_dir = coll_dir / POSTMAN_V3_UNSAFE_FILENAME.sub("_", folder["info"]["name"])
        (folder_dir / ".resources").mkdir(parents=True, exist_ok=True)
        (folder_dir / ".resources" / "definition.yaml").write_text(
            to_yaml(postman_v3_folder_definition(folder)), encoding="utf-8"
        )
        file_count += 1
        for req in folder["items"]:
            fname = POSTMAN_V3_UNSAFE_FILENAME.sub("_", req["info"]["name"]) + ".request.yaml"
            (folder_dir / fname).write_text(to_yaml(postman_v3_request(req)), encoding="utf-8")
            file_count += 1
    env_dir = root / "environments"
    env_dir.mkdir(parents=True, exist_ok=True)
    for env in collection.get("config", {}).get("environments", []):
        (env_dir / f"{POSTMAN_V3_UNSAFE_FILENAME.sub('_', env['name'])}.environment.yaml").write_text(
            to_yaml(postman_v3_environment(env)), encoding="utf-8"
        )
        file_count += 1
    return file_count


def default_out_path(fmt):
    default = {
        "tree": "dist/opencollection/vk-api",
        "bundled": "dist/opencollection/vk-api.yaml",
        "postman": "dist/postman/vk-api.postman_collection.json",
        "openapi": "dist/openapi/vk-api.yaml",
        "postman-v3": "dist/postman/vk-api-local",
    }
    return pathlib.Path(default[fmt])


def main():
    parser = argparse.ArgumentParser(description="Generate OpenCollection collection from vk-api-schema")
    parser.add_argument("--schema-dir", default=None, type=pathlib.Path)
    parser.add_argument("--out", default=None, type=pathlib.Path)
    parser.add_argument("--format", choices=("tree", "bundled", "postman", "openapi", "postman-v3"), default="tree")
    parser.add_argument("--api-version", default="latest", help="API version, or 'latest' to fetch from dev portal")
    parser.add_argument("--name", default="VK API")
    parser.add_argument("--all", action="store_true", help="include nodoc/hidden methods (default: public only)")
    parser.add_argument("--descriptions", default=SCRIPT_DIR / "data/parameter_descriptions.json", help="RU descriptions cache from dev portal")
    parser.add_argument("--dump-json", type=pathlib.Path, help="also dump the built object as JSON for verification")
    args = parser.parse_args()
    if args.schema_dir is None:
        args.schema_dir = default_schema_dir()
    if args.out is None:
        args.out = default_out_path(args.format)

    env_paths = []
    if args.format == "openapi":
        doc, stats = build_openapi(
            args.schema_dir, resolve_api_version(args.api_version), args.name, args.descriptions, args.all
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(to_yaml(doc), encoding="utf-8")
        size = f"{args.out.stat().st_size / 1024 / 1024:.1f} MB"
        file_count = 1
        print(
            f"format={args.format} operations={stats['operations']} schemas={stats['schemas']} "
            f"files={file_count} collisions={stats['collisions']} encodings={','.join(stats['encodings'])} "
            f"ru_descriptions={stats['ru_descriptions']} out={args.out} ({size})"
        )
        return None
    collection, stats = build(args.schema_dir, resolve_api_version(args.api_version), args.name, args.descriptions, args.all)
    if args.format == "bundled":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(to_yaml({**collection, "bundled": True}), encoding="utf-8")
        size = f"{args.out.stat().st_size / 1024 / 1024:.1f} MB"
        file_count = 1
    elif args.format == "postman":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(dump_postman(collection), encoding="utf-8")
        env_paths = []
        for i, env in enumerate(collection.get("config", {}).get("environments", [])):
            if i == 0:
                env_path = postman_environment_path(args.out)
            else:
                env_path = args.out.parent / f"{SAFE_FILENAME.sub('_', env['name'])}.postman_environment.json"
            env_path.write_text(dump_postman_environment(env), encoding="utf-8")
            env_paths.append(env_path)
        size = f"{args.out.stat().st_size / 1024 / 1024:.1f} MB"
        file_count = 1 + len(env_paths)
    elif args.format == "postman-v3":
        file_count = write_postman_v3(collection, args.out)
        total = sum(f.stat().st_size for f in args.out.rglob("*") if f.is_file())
        size = f"{total / 1024 / 1024:.1f} MB"
    else:
        file_count = write_tree(collection, args.out)
        total = sum(f.stat().st_size for f in args.out.rglob("*") if f.is_file())
        size = f"{total / 1024 / 1024:.1f} MB"
    if args.dump_json:
        args.dump_json.parent.mkdir(parents=True, exist_ok=True)
        args.dump_json.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")
    print(
        f"format={args.format} folders={stats['folders']} requests={stats['requests']} "
        f"files={file_count} collisions={stats['collisions']} encodings={','.join(stats['encodings'])} "
        f"ru_descriptions={stats['ru_descriptions']} out={args.out}"
        + (f" +{len(env_paths)} environment file(s)" if env_paths else "")
        + f" ({size})"
    )


if __name__ == "__main__":
    sys.exit(main())
