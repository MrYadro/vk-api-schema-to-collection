# vk-api-schema-to-collection

Генерация коллекций [Bruno](https://usebruno.com) / [OpenCollection](https://spec.opencollection.com) / [Postman](https://www.postman.com) / [Yaak](https://yaak.app) / [Insomnia](https://insomnia.rest) / [Hoppscotch](https://hoppscotch.io) и спецификации [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1) из публичной схемы [VKCOM/vk-api-schema](https://github.com/VKCOM/vk-api-schema).

- Папки-категории, POST-запросы (`category.method` → папка `Category`)
- Bearer-авторизация на коллекции (`{{accessToken}}`), запросы и папки наследуют auth
- Параметры — form-urlencoded body; обязательные включены, опциональные выключены
- Enum-параметры — по одной выключенной строке на каждое значение, значения резолвятся через `$ref` в objects.json
- Русские описания методов и параметров с dev.vk.ru (фолбэк — английские из схемы)
- Postman: коллекция v2.1 (JSON) + файл окружения `api.vk.ru`, автотест на коды ошибок VK через `pm.test`
- Postman Native Git (Local View): дерево Collection V3 YAML (`postman/collections/…`) — открывается в Postman через Files → Open folder, Git-native
- Yaak: sync-папка YAML (`yaak.<id>.yaml`) — Open Workspace или `yaak import`, git-native, с `--merge`
- Insomnia: v4 JSON для GUI-импорта + v5 YAML Git Sync папка (headless `inso` CLI), v5 — с `--merge`
- Hoppscotch: коллекция v12 + файл окружения с `secret`-переменными
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
python3 generate_collection.py --format yaak
python3 generate_collection.py --format insomnia
python3 generate_collection.py --format insomnia-v5
python3 generate_collection.py --format hoppscotch
```

Дефолтный вывод — по папкам форматов в `dist/`:

```
dist/
├── opencollection/    # tree (Bruno: File → Open Collection) и bundled YAML
├── postman/           # vk-api.postman_collection.json + окружение; vk-api-local/ — Native Git дерево
├── openapi/           # OpenAPI 3.1 spec (Swagger UI / codegen)
├── yaak/              # sync-папка Yaak (yaak.<id>.yaml)
├── insomnia/          # vk-api.insomnia.json (v4 GUI-импорт); vk-api-local/ — Git Sync папка v5
└── hoppscotch/        # коллекция vk-api.hoppscotch.json + окружение api.vk.ru.hoppscotch.env.json
```

В Bruno: File → Open Collection → выбрать папку `dist/opencollection/vk-api`.
В Postman: Import → File → `dist/postman/vk-api.postman_collection.json`, затем импортировать окружение
`dist/postman/vk-api.postman_environment.json` и вписать токен в `accessToken`.
В Postman Local View: Files → Open folder → `dist/postman/vk-api-local` (манифест `.postman/` Postman создаст сам).
В Yaak: Open Workspace → `dist/yaak/vk-api`.
В Insomnia: Import → `dist/insomnia/vk-api.insomnia.json` (v4) или Git Sync-папка `dist/insomnia/vk-api-local` (v5).
В Hoppscotch: Collections → Import → `dist/hoppscotch/vk-api.hoppscotch.json`, затем окружение `api.vk.ru.hoppscotch.env.json`.
Токен вписать в секретную переменную `accessToken` окружения `api.vk.ru`;
`baseUrl` и `apiVersion` работают без выбора окружения (collection-level переменные).

## Обновление существующей коллекции

Регулярная генерация полностью перезаписывает вывод. Чтобы вести коллекцию руками
(заполненные значения параметров, токены в окружении) и актуализировать её из схемы:

```sh
python3 generate_collection.py --format tree --merge       # обновить, сохранив правки
python3 generate_collection.py --format postman-v3 --merge # то же для Postman Local View
python3 generate_collection.py --format yaak --merge       # sync-папка Yaak
python3 generate_collection.py --format insomnia-v5 --merge # Git Sync папка Insomnia
python3 generate_collection.py --format tree --prune       # полная перегенерация + удалить устаревшие файлы
```

Правила: значение параметра/переменной сохраняется, если оно отличается от
генерируемого (пустые генерируемые значения не защищаются); `apiVersion` всегда
из свежей схемы; методы, пропавшие из схемы, остаются (удаляются только с `--prune`;
свои запросы в сгенерированных папках `--prune` тоже удалит). Если вы вручную
заменили значение строки `v` (не `{{apiVersion}}`), оно сохранится как есть.
Требует PyYAML (`pip install pyyaml`).

## Скрипты

| Скрипт | Назначение |
| --- | --- |
| `fetch_parameter_descriptions.py` | Обходит методы через `documentation.getPage` dev-портала, кэш — `data/parameter_descriptions.json`. |
| `generate_collection.py` | Строит коллекцию. |
| `core.py` + `formats/` | Общее ядро генерации и модули форматов (точка расширения — см. «Как добавить формат вывода»). |
| `validate_collection.py` | Валидирует сгенерированное: OpenCollection (tree/bundled), Postman (коллекция/окружение) и OpenAPI 3.1 — по официальным JSON Schema; postman-v3, yaak, insomnia (v4/v5), hoppscotch — структурные проверки. Формат определяется по пути. |

## Как добавить формат вывода

Форматы живут в `formats/` — по модулю на формат, каждый экспортирует `FormatSpec`:

1. Создайте `formats/<имя>.py`: функции `write(payload, out) -> (file_count, note)`,
   опционально `build(ctx)` (по умолчанию — общая модель коллекции через
   `formats.build_collection`), `matches(path)` и `validate(path)` для валидатора.
2. Зарегистрируйте спеку в `FORMATS` в `formats/__init__.py`.
3. Для поддержки `--merge`: `load_existing(out)` и `prune_orphans(out, collection)`
   в том же модуле плюс `supports_merge=True` (см. `formats/opencollection.py`).
4. Чтобы валидатор распознавал вывод формата — добавьте имя в `SNIFF_PRIORITY`
   в `validate_collection.py` и свою OK-строку печати в его `main()`
   (по умолчанию — `OK: N folders, M requests`).

`--format`, дефолтный путь вывода и статистика печати подхватываются из реестра
автоматически.

## Инварианты всех экспортов

Общие требования к любому формату вывода (проверяются тестами форматов):

- **Сортировка**: папки и запросы — в порядке модели (алфавит по именам);
  служебная папка `_Meta` (проверка токена + песочница `execute`) всегда первая.
  Форматы с явными ключами порядка (insomnia `metaSortKey`/`sortKey`) пишут их
  с шагом 1000 в порядке модели; форматы с файловым порядком (tree, yaak, v3)
  следуют порядку обхода.
- **Auth**: Bearer-токен задан один раз на верхнем уровне (коллекция/корневая
  папка/workspace), запросы и папки наследуют; плейсхолдер токена — в синтаксисе
  клиента (`{{accessToken}}` / `<<accessToken>>` / `${[ env.accessToken ]}`).
- **Параметры**: form-urlencoded; обязательные включены, опциональные выключены
  (где формат поддерживает per-param state), enum — по строке на значение;
  строка `v` — плейсхолдер версии API.
- **Секреты**: переменные-токены идут с пометкой секрета там, где формат
  позволяет (hoppscotch `secret`, insomnia v4 `kvPairData type: secret`),
  иначе — пустым значением для заполнения в клиенте.
- **Переменные**: `baseUrl` и `apiVersion` всегда из свежей генерации; при
  `--merge` пользовательские значения защищаются (см. «Обновление существующей
  коллекции»).
- **Автотесты**: скрипт проверки кодов ошибок VK (HTTP 200 + поле `error`,
  подсказки по частым кодам) пишется во все форматы с поддержкой scripting,
  в диалекте клиента: Bruno `test/expect`, Postman `pm.test`,
  Insomnia `insomnia.test`, Hoppscotch `pw.test`. Размещение — один раз на
  самом верхнем уровне, где формат позволяет, с наследованием всеми запросами:
  коллекция (OpenCollection, Postman v2.1/v3), корневая папка (Insomnia —
  afterResponse наследуется от всех предков). Исключение — Hoppscotch: в формате
  нет папочного наследования, скрипт у каждого запроса. Yaak и OpenAPI
  scripting не поддерживают.
- **Цвет**: окружения несут VK-blue `#0077FF` из модели везде, где формат
  позволяет (OpenCollection/insomnia v4+v5/yaak — hex; Postman v2.1/v3 — hue 212,
  цветовое колесо Postman); hoppscotch и openapi цветов окружений не поддерживают.
- **Описания**: markdown-документация запроса и папки (`docs` модели) попадает
  в поле description формата, если оно есть.

## Сравнение форматов

Срез на сентябрь 2026.

| Формат | Секреты | Docs запроса | Docs папки | Param description | Тесты | Merge | Импорт | CLI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tree (Bruno) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | папка (Bruno) | — |
| bundled (OpenCollection) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| postman v2.1 | ✓ | ✓ | ✓ | ✓ | ✓ | — | GUI | — |
| postman-v3 (Native Git) | частично¹ | ✓ | ✓ | ✓ | ✓ | ✓ | папка (Postman) | — |
| openapi | — | ✓ | — | ✓ | — | — | GUI/кодоген | — |
| yaak | частично² | ✓ | ✓ | —³ | — | ✓⁵ | папка/`yaak import` | `yaak` CLI |
| insomnia v4 | ✓⁴ | ✓ | ✓ | ✓ | ✓⁶ | — | GUI | — |
| insomnia-v5 | частично | ✓ | ✓ | ✓ | ✓⁶ | ✓ | папка/git sync | `inso` |
| hoppscotch | ✓ | ✓ | ✓ | — | ✓⁷ | — | GUI | `hopp test` |

¹ accessToken в definition.yaml перегенерируется; ² флага нет, шифрование при
заполнении; ³ у form-строк Yaak нет description; ⁴ kvPairData `type: secret`
(финализируется эталонным тестом); ⁵ id файлов yaak позиционные: вставка метода
в середину схемы пересчитывает суффиксы — ожидайте diff-шум в git, данные при
merge сохраняются; ⁶ один скрипт на корневой папке — рантайм Insomnia
наследует afterResponse-скрипты всех предков каждому запросу (проверено по
исходникам network.ts); ⁷ папочного наследования в формате нет — скрипт у
каждого запроса.

## Параметры запуска

### generate_collection.py

| Флаг | По умолчанию | Описание |
| --- | --- | --- |
| `--format` | `tree` | Формат вывода: `tree` \| `bundled` \| `postman` \| `postman-v3` \| `openapi` \| `yaak` \| `insomnia` \| `insomnia-v5` \| `hoppscotch`. |
| `--out` | по формату (`dist/…`) | Путь вывода: каталог для `tree`/`postman-v3`/`yaak`/`insomnia-v5`/`hoppscotch`, файл для остальных. |
| `--schema-dir` | `~/Dev/vk-api-schema` | Путь к клону vk-api-schema (или переменная `VK_API_SCHEMA_DIR`). |
| `--api-version` | `latest` | Версия API; `latest` — взять актуальную с dev-портала. |
| `--name` | `VK API` | Имя коллекции. |
| `--descriptions` | `data/parameter_descriptions.json` | Кэш русских описаний параметров с dev-портала. |
| `--dump-json PATH` | — | Дополнительно выгрузить построенный объект коллекции в JSON. |
| `--merge` | выкл | Обновить существующий вывод вместо замены (tree, bundled, postman-v3, yaak, insomnia-v5): значения параметров и токены пользователя сохраняются, новые методы добавляются, описания актуализируются, сортировка пересчитывается. |
| `--prune` | выкл | Удалить запросы и папки, отсутствующие в новой схеме (в т.ч. свои запросы в сгенерированных папках). Работает и без `--merge` — как чистка устаревших файлов. |

### fetch_parameter_descriptions.py

| Флаг | По умолчанию | Описание |
| --- | --- | --- |
| `--schema-dir` | `~/Dev/vk-api-schema` | Путь к клону vk-api-schema. |
| `--out` | `data/parameter_descriptions.json` | Файл кэша описаний. |
| `--api-version` | `5.190` | Версия API для запросов к dev-порталу. |
| `--rps` | `3.0` | Ограничение запросов в секунду. |
| `--limit N` | `0` (все) | Обновить только первые N отсутствующих методов. |
| `--save-every N` | `50` | Сохранять кэш каждые N методов. |
| `--method X` | — | Получить описание одного метода (для отладки). |
| `--token-file PATH` | временный путь | Файл с токеном вместо анонимного токена dev-портала. |
| `--use-file-token` | выкл | Принудительно использовать токен из `--token-file`. |

### validate_collection.py

| Аргумент | Описание |
| --- | --- |
| `PATH` | Что валидировать: bundled `.yaml`, каталог `tree`, postman `.json` (коллекция/окружение), каталог `postman-v3`, openapi `.yaml`, каталог `yaak`, `*.insomnia.json` (v4), каталог insomnia-v5, файлы `*.hoppscotch.json` (коллекция/окружение). Формат определяется по пути. |
| `--schema PATH` | Локальная JSON Schema вместо онлайн (opencollection). |

Окружения: `VK_API_SCHEMA_DIR` — путь к клону vk-api-schema (по умолчанию `~/Dev/vk-api-schema`).
Схема ищется в `$VK_API_SCHEMA_DIR/api_schema` или в корне клона.
Версия API: `--api-version latest` (по умолчанию, берётся с dev-портала) или явная, например `5.199`.

Валидация Postman-окружения использует официальную онлайн-схему; schema.getpostman.com
отдаёт 403 на environment.json — в этом случае валидация окружения пропускается с предупреждением.

## Тесты

```sh
python3 -m unittest discover -s tests -p "test_*.py"
```

## CI

Workflow `.github/workflows/release.yml` (ручной запуск, Actions → release):

- определяет версию API — из input или через `documentation.getLastVersion`;
- клонирует vk-api-schema, обновляет кэш русских описаний;
- собирает все форматы и валидирует: OpenCollection/Postman/OpenAPI — по официальным JSON Schema; postman-v3, yaak, insomnia, hoppscotch — структурные проверки;
- пакует в шесть zip-артефактов, по клиенту на файл: `opencollection.zip` (tree + bundled), `postman.zip` (коллекция v2.1 + окружение + `vk-api-local/` Native Git дерево), `openapi.zip`, `yaak.zip` (sync-папка), `insomnia.zip` (v4 JSON + v5 Git Sync папка), `hoppscotch.zip` (коллекция + окружение);
- создаёт релиз `VK API <version>` с тегом `v<version>` (существующий тег не перезаписывается, если не включить `force`).
