# vk-api-schema-to-bruno

Генерация коллекции [Bruno](https://usebruno.com) / [OpenCollection](https://spec.opencollection.com) из публичной схемы [VKCOM/vk-api-schema](https://github.com/VKCOM/vk-api-schema).

- Папки-категории, POST-запросы (`category.method` → папка `Category`)
- Bearer-авторизация на коллекции (`{{accessToken}}`), запросы и папки — `auth: inherit`
- Параметры — form-urlencoded body; обязательные включены, опциональные выключены
- Enum-параметры — по одной выключенной строке на каждое значение, значения резолвятся через `$ref` в objects.json
- Русские описания методов и параметров с dev.vk.ru (фолбэк — английские из схемы)
- Только stdlib Python 3, зависимостей нет

## Использование

```sh
git clone https://github.com/VKCOM/vk-api-schema ~/Dev/vk-api-schema

python3 fetch_parameter_descriptions.py   # обновить кэш русских описаний (анонимный токен dev.vk.ru)
python3 generate_opencollection.py        # bruno-collection/vk-api (tree-формат Bruno)
python3 generate_opencollection.py --format bundled --out vk-api.yaml
```

В Bruno: File → Open Collection → выбрать папку `bruno-collection/vk-api`.
Токен вписать в секретную переменную `accessToken` окружения `api.vk.ru`;
`baseUrl` и `apiVersion` работают без выбора окружения (collection-level переменные).

## Скрипты

| Скрипт | Назначение |
| --- | --- |
| `fetch_parameter_descriptions.py` | Обходит методы через `documentation.getPage` dev-портала, кэш — `data/parameter_descriptions.json`. Флаги: `--all`, `--rps`, `--method X`, `--schema-dir`. |
| `generate_opencollection.py` | Строит коллекцию. Флаги: `--format tree\|bundled`, `--all`, `--api-version`, `--schema-dir`, `--descriptions`, `--out`. |

Окружения: `VK_API_SCHEMA_DIR` — путь к клону vk-api-schema (по умолчанию `~/Dev/vk-api-schema`).
Схема ищется в `$VK_API_SCHEMA_DIR/api_schema` или в корне клона.
Версия API: `--api-version latest` (по умолчанию, берётся с dev-портала) или явная, например `5.199`.

## CI

Workflow `.github/workflows/release.yml` (ручной запуск, Actions → release):

- определяет версию API — из input или через `documentation.getLastVersion`;
- клонирует vk-api-schema, обновляет кэш русских описаний;
- собирает bundled YAML и zip tree-коллекцию, валидирует по официальной JSON Schema;
- создаёт релиз `VK API <version>` с тегом `v<version>` и артефактами (существующий тег не перезаписывается, если не включить `force`).

