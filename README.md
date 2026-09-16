# vk-api-schema-to-collection

Генерация коллекций [Bruno](https://usebruno.com) / [OpenCollection](https://spec.opencollection.com) / [Postman](https://www.postman.com) из публичной схемы [VKCOM/vk-api-schema](https://github.com/VKCOM/vk-api-schema).

- Папки-категории, POST-запросы (`category.method` → папка `Category`)
- Bearer-авторизация на коллекции (`{{accessToken}}`), запросы и папки наследуют auth
- Параметры — form-urlencoded body; обязательные включены, опциональные выключены
- Enum-параметры — по одной выключенной строке на каждое значение, значения резолвятся через `$ref` в objects.json
- Русские описания методов и параметров с dev.vk.ru (фолбэк — английские из схемы)
- Postman: коллекция v2.1 (JSON) + файл окружения `api.vk.ru`, автотест на коды ошибок VK через `pm.test`
- Только stdlib Python 3 (для валидации — pyyaml + jsonschema)

## Использование

```sh
git clone https://github.com/VKCOM/vk-api-schema ~/Dev/vk-api-schema

python3 fetch_parameter_descriptions.py   # обновить кэш русских описаний (анонимный токен dev.vk.ru)
python3 generate_collection.py            # dist/vk-api (tree-формат Bruno)
python3 generate_collection.py --format bundled --out vk-api.yaml
python3 generate_collection.py --format postman
```

В Bruno: File → Open Collection → выбрать папку `dist/vk-api`.
В Postman: Import → File → `dist/vk-api.postman_collection.json`, затем импортировать окружение
`dist/vk-api.postman_environment.json` и вписать токен в `accessToken`.
Токен вписать в секретную переменную `accessToken` окружения `api.vk.ru`;
`baseUrl` и `apiVersion` работают без выбора окружения (collection-level переменные).

## Скрипты

| Скрипт | Назначение |
| --- | --- |
| `fetch_parameter_descriptions.py` | Обходит методы через `documentation.getPage` dev-портала, кэш — `data/parameter_descriptions.json`. Флаги: `--all`, `--rps`, `--method X`, `--schema-dir`. |
| `generate_collection.py` | Строит коллекцию. Флаги: `--format tree\|bundled\|postman`, `--all`, `--api-version`, `--schema-dir`, `--descriptions`, `--out`. |
| `validate_collection.py` | Валидирует сгенерированное по официальным JSON Schema: OpenCollection (tree/bundled) и Postman (коллекция/окружение). Формат определяется по пути. |

Окружения: `VK_API_SCHEMA_DIR` — путь к клону vk-api-schema (по умолчанию `~/Dev/vk-api-schema`).
Схема ищется в `$VK_API_SCHEMA_DIR/api_schema` или в корне клона.
Версия API: `--api-version latest` (по умолчанию, берётся с dev-портала) или явная, например `5.199`.

Валидация Postman-окружения использует официальную схему; если schema.getpostman.com
недоступна (CDN отдаёт 403 на environment.json), берётся вендоренная копия `schemas/postman-environment-v2.1.0.json`.

## Тесты

```sh
python3 -m unittest discover -p "test_*.py"
```

## CI

Workflow `.github/workflows/release.yml` (ручной запуск, Actions → release):

- определяет версию API — из input или через `documentation.getLastVersion`;
- клонирует vk-api-schema, обновляет кэш русских описаний;
- собирает bundled YAML, zip tree-коллекцию, Postman-коллекцию и окружение;
- валидирует всё по официальным JSON Schema;
- создаёт релиз `VK API <version>` с тегом `v<version>` и артефактами (существующий тег не перезаписывается, если не включить `force`).
