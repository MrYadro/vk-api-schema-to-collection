# vk-api-schema-to-collection

Генерация коллекций [Bruno](https://usebruno.com) / [OpenCollection](https://spec.opencollection.com) / [Postman](https://www.postman.com) / [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1) из публичной схемы [VKCOM/vk-api-schema](https://github.com/VKCOM/vk-api-schema).

- Папки-категории, POST-запросы (`category.method` → папка `Category`)
- Bearer-авторизация на коллекции (`{{accessToken}}`), запросы и папки наследуют auth
- Параметры — form-urlencoded body; обязательные включены, опциональные выключены
- Enum-параметры — по одной выключенной строке на каждое значение, значения резолвятся через `$ref` в objects.json
- Русские описания методов и параметров с dev.vk.ru (фолбэк — английские из схемы)
- Postman: коллекция v2.1 (JSON) + файл окружения `api.vk.ru`, автотест на коды ошибок VK через `pm.test`
- Postman Native Git (Local View): дерево Collection V3 YAML (`postman/collections/…`) — открывается в Postman через Files → Open folder, Git-native
- OpenAPI 3.1: реальные JSON Schema параметров и ответов (`responses.json`), components/schemas с namespace по категориям, `VkError` для ошибок VK (HTTP 200)
- Только stdlib Python 3 (для валидации — pyyaml + jsonschema)

## Использование

```sh
git clone https://github.com/VKCOM/vk-api-schema ~/Dev/vk-api-schema

python3 fetch_parameter_descriptions.py   # обновить кэш русских описаний (анонимный токен dev.vk.ru)
python3 generate_collection.py            # dist/opencollection/vk-api (tree-формат)
python3 generate_collection.py --format bundled
python3 generate_collection.py --format postman
python3 generate_collection.py --format postman-v3
python3 generate_collection.py --format openapi
```

Дефолтный вывод — по папкам форматов в `dist/`:

```
dist/
├── opencollection/    # tree (Bruno: File → Open Collection) и bundled YAML
├── postman/           # vk-api.postman_collection.json + окружение; vk-api-local/ — Native Git дерево
└── openapi/           # OpenAPI 3.1 spec (Swagger UI / codegen)
```

В Bruno: File → Open Collection → выбрать папку `dist/opencollection/vk-api`.
В Postman: Import → File → `dist/postman/vk-api.postman_collection.json`, затем импортировать окружение
`dist/postman/vk-api.postman_environment.json` и вписать токен в `accessToken`.
В Postman Local View: Files → Open folder → `dist/postman/vk-api-local` (манифест `.postman/` Postman создаст сам).
Токен вписать в секретную переменную `accessToken` окружения `api.vk.ru`;
`baseUrl` и `apiVersion` работают без выбора окружения (collection-level переменные).

## Скрипты

| Скрипт | Назначение |
| --- | --- |
| `fetch_parameter_descriptions.py` | Обходит методы через `documentation.getPage` dev-портала, кэш — `data/parameter_descriptions.json`. Флаги: `--all`, `--rps`, `--method X`, `--schema-dir`. |
| `generate_collection.py` | Строит коллекцию. Флаги: `--format tree\|bundled\|postman\|postman-v3\|openapi`, `--all`, `--api-version`, `--schema-dir`, `--descriptions`, `--out`. |
| `validate_collection.py` | Валидирует сгенерированное по официальным JSON Schema: OpenCollection (tree/bundled), Postman (коллекция/окружение), OpenAPI 3.1; postman-v3 — структурные проверки. Формат определяется по пути. |

Окружения: `VK_API_SCHEMA_DIR` — путь к клону vk-api-schema (по умолчанию `~/Dev/vk-api-schema`).
Схема ищется в `$VK_API_SCHEMA_DIR/api_schema` или в корне клона.
Версия API: `--api-version latest` (по умолчанию, берётся с dev-портала) или явная, например `5.199`.

Валидация Postman-окружения использует официальную онлайн-схему; schema.getpostman.com
отдаёт 403 на environment.json — в этом случае валидация окружения пропускается с предупреждением.

## Тесты

```sh
python3 -m unittest discover -p "test_*.py"
```

## CI

Workflow `.github/workflows/release.yml` (ручной запуск, Actions → release):

- определяет версию API — из input или через `documentation.getLastVersion`;
- клонирует vk-api-schema, обновляет кэш русских описаний;
- собирает все форматы и валидирует по официальным JSON Schema (postman-v3 — структурные проверки);
- пакует в четыре zip-артефакта: `opencollection.zip` (tree + bundled), `postman.zip` (коллекция + окружение), `postman-v3.zip` (Native Git дерево), `openapi.zip`;
- создаёт релиз `VK API <version>` с тегом `v<version>` (существующий тег не перезаписывается, если не включить `force`).
