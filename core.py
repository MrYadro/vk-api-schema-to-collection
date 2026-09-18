import datetime
import json
import os
import pathlib
import re
import shutil
import sys
import urllib.parse
import urllib.request

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


OC_SCHEMA_URL = "https://schema.opencollection.com/opencollection/v1.0.0.json"
POSTMAN_COLLECTION_SCHEMA_URL = "https://schema.postman.com/collection/json/v2.1.0/draft-07/collection.json"
POSTMAN_ENVIRONMENT_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/environment.json"
OPENAPI_SCHEMA_URL = "https://spec.openapis.org/oas/3.1/schema/2022-10-07"


def load_schema(path, url):
    if path:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_document(path):
    path = pathlib.Path(path)
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def jsonschema_validator(schema):
    from jsonschema.validators import validator_for

    return validator_for(schema)(schema)


def allow_postman_secret_type(schema):
    variable = schema.get("definitions", {}).get("variable") or schema.get("$defs", {}).get("variable")
    if variable:
        enum = variable.get("properties", {}).get("type", {}).get("enum")
        if enum and "secret" not in enum:
            enum.append("secret")
    return schema


def require_yaml():
    try:
        import yaml
    except ImportError:
        raise SystemExit("--merge/--prune need PyYAML: pip install pyyaml")
    return yaml


BACKUP_LIMIT = 10


def backup_existing(out, limit=BACKUP_LIMIT):
    out = pathlib.Path(out)
    if not out.exists():
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = out.parent / f"{out.name}.bak-{stamp}"
    if out.is_dir():
        shutil.copytree(out, target)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out, target)
    backups = sorted(out.parent.glob(f"{out.name}.bak-*"))
    for stale in backups[: -limit] if limit else backups:
        if stale.is_dir():
            shutil.rmtree(stale)
        else:
            stale.unlink()
    return target
