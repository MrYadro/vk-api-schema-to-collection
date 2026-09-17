# Новые форматы экспорта: Yaak, Insomnia, Hoppscotch + таблица сравнения

Дата: 2026-09-17
Статус: утверждённый дизайн

## Контекст и цель

Проект имеет реестр форматов (`formats/`, `FormatSpec`) — точку расширения «модуль +
строка регистрации». Добавляем четыре клиентских формата по итогам исследования:

| Формат | Режим | Merge | Обоснование |
| --- | --- | --- | --- |
| `yaak` | sync-папка YAML | ✓ | клиент работает из локальной папки |
| `insomnia` | v4 JSON (GUI-импорт) | — | секрет-флаг kvPairData, полный импорт |
| `insomnia-v5` | Git Sync папка v5 YAML | ✓ | локальная папка + headless `inso` CLI |
| `hoppscotch` | collection+env JSON (GUI-импорт) | — | urlencoded — плоская строка, round-trip теряет атрибуты |

Kreya и HTTPie не строим (см. «Не входит»); оба отражаются в таблице сравнения.

Правило merge (решение пользователя): merge поддерживается только у форматов,
где клиент живёт в локальной папке; GUI-импорт-форматам merge не нужен.

## Область

4 новых модуля `formats/{yaak,insomnia,insomnia_v5,hoppscotch}.py` со спеками
(генерация + валидация; yaak/insomnia-v5 — плюс merge: `load_existing`/`prune_orphans`),
расширение реестра до 9 форматов, структурные валидаторы, README-таблица сравнения,
тесты. Внешний CLI-контракт не меняется (единый print; golden-тесты расширяются).

## Формат `yaak` (sync-папка)

Вывод — каталог с файлами `yaak.<id>.yaml` (по файлу на ресурс, поле `model`):

- `yaak.wrk_1.yaml` — `model: workspace`: `{name, description: <collection docs md>}`,
  `authenticationType: bearer`, `authentication: {token: "${[ env.accessToken ]}"}`.
- `yaak.env_1.yaml` — `model: environment`: `{name: api.vk.ru, variables: [{name, value, enabled: true}]}`
  (секретные переменные — с пустым значением; Yaak шифрует при заполнении через GUI).
- `yaak.fl_<n>.yaml` — `model: folder`: `{id, workspaceId, folderId: null, name,
  description: <folder docs md>}`; один уровень папок, как в модели.
- `yaak.rq_<n>.yaml` — `model: http_request`: `{id, workspaceId, folderId, name,
  method: POST, url, bodyType: application/x-www-form-urlencoded,
  body: {form: [{name, value, enabled: not disabled}]}, description: <request docs md>}`.

ID детерминированные (`wrk_1`, `env_1`, `fl_<n>`, `rq_<n>` по порядку обхода) —
стабильность между прогонками для merge/prune.

Конвертация плейсхолдеров: `{{var}}` → `${[ env.var ]}` (в url и значениях строк;
`v` → `${[ env.apiVersion ]}`).

Merge: `load_existing` читает `yaak.*.yaml` → полная модель (обратная конвертация
`${[ env.var ]}` → `{{var}}`; `enabled` → `disabled: not enabled`; docs → description)
с `keep_old_items=True`; `prune_orphans` удаляет `yaak.*.yaml`, чьи id не входят в
новый вывод. `default_out: dist/yaak/vk-api`.

## Формат `insomnia` (v4 JSON)

Один файл `{_type: export, __export_format: 4, resources: [...]}`:

- `workspace` (`__WORKSPACE_ID__`, name, scope: collection).
- Корневая `request_group` «VK API» с `authentication` (bearer, токен
  `{{ accessToken }}`) — collection-level auth в Insomnia нет, носитель — корневая
  группа; дочерние группы-папки наследуют.
- `request_group` на папку: `{parentId, name, description: <folder docs md>}`.
- `request`: `{parentId, name, method: POST, url: "{{ baseUrl }}/method/<name>",
  body: {mimeType: application/x-www-form-urlencoded, params: [{name, value,
  description?, disabled?}]}, description: <request docs md>}`.
- base `environment` (`__BASE_ENVIRONMENT_ID__`/`__ENV_1__`): переменные
  baseUrl/apiVersion; секретные (токены) — с пустым значением и пометкой секрета
  (kvPairData `type: "secret"`, если формат импорта поддерживает — фиксируется
  эталонным тестом по исходникам `insomnia-4.ts`; иначе — `data` + пустые значения,
  потеря фиксируется в таблице).

`{{ var }}` — синтаксис совпадает с моделью, конвертация не нужна.
Без merge. `matches`: имя файла содержит `insomnia` и `.json`.
Структурный валидатор (офлайн): `__export_format == 4`, счётчики ресурсов по `_type`.
`default_out: dist/insomnia/vk-api.insomnia.json`.

## Формат `insomnia-v5` (Git Sync папка)

Вывод — каталог v5 YAML (`type: collection.insomnia.rest/5.0`): дерево
`collection:` (папки с `children`, запросы), `environments:` (base + subEnvironments),
`cookieJar`. Содержимое полей — как у v4 (description запросов/папок, params с
description/disabled, Bearer на корневой папке). Секретов-флага в v5 нет —
токены subEnvironments с пустыми значениями (таблица: «частично»).

Единственный открытый деталь-вопрос — точный layout имён файлов Git Sync-папки:
устанавливается при реализации по исходникам `insomnia-v5.ts` / git-sync Insomnia
и фиксируется эталонными тестами (прогон → чтение → merge). Loader — полная модель
(для `keep_old_items=True`), prune — по файлам вне нового вывода.
`default_out: dist/insomnia/vk-api-local`.

## Формат `hoppscotch` (collection + env JSON)

Два файла в `dist/hoppscotch/`:

- Коллекция `vk-api.json`: `{v: 12, name, folders: [{v: 12, name, folders: [],
  requests: [...], auth: {authType: inherit, authActive: true}, headers: [],
  variables: [], description: <folder docs md>, preRequestScript: "", testScript: ""}],
  requests: [], auth: {authType: bearer, authActive: true, token: "<<accessToken>>"},
  headers: [], variables: [], description: <collection docs>, preRequestScript: "",
  testScript: ""}`.
- Запрос (`v: "17"` — строка!): `{name, method: POST,
  endpoint: "<<baseUrl>>/method/<name>", params: [], headers: [],
  auth: {authType: inherit, authActive: true},
  body: {contentType: application/x-www-form-urlencoded, body: "<k>: <v>\n…"},
  requestVariables: [], responses: {}, preRequestScript: "", testScript: "",
  description: <request docs md>}`. Синтаксис переменных `<<var>>`.
- Env `api.vk.ru.env.json`: `[{v: 2, id, name: api.vk.ru, variables: [{key,
  initialValue, currentValue, secret}]}` — у токенов `secret: true`.

Body-строка: **все** параметры модели (обязательные и выключенные) как строки
`name: value` — per-param enabled/description в формате отсутствуют (VK игнорирует
пустые значения; потеря фиксируется в таблице). `write` возвращает
`(file_count, note)` с note `+1 environment file(s)`.
Без merge (round-trip терял бы disabled). `matches`: имя содержит `hoppscotch` и
`.json`. Структурный валидатор (v-поля, счётчики). `default_out: dist/hoppscotch`.

## Реестр, CLI, валидация

- 4 спеки: `model_based=True`, `stats_keys=("folders", "requests")`;
  `supports_merge=True` только у `yaak`/`insomnia-v5` (текст ошибки
  `--merge/--prune are only supported for tree, bundled, postman-v3, yaak and
  insomnia-v5` соберётся из реестра автоматически).
- `SNIFF_PRIORITY` пополняется (порядок — конкретика плана, эвристики:
  openapi → insomnia → hoppscotch → postman → postman-v3 → yaak → insomnia-v5 →
  bundled → tree); `matches`: yaak — каталог с `yaak.*.yaml`; insomnia-v5 — каталог,
  чей первый `*.yml/yaml` содержит `collection.insomnia.rest/5.0`.
- Валидаторы всех четырёх — структурные офлайн (ленивый yaml), печать OK-строк в
  `validate_collection.main()` по образцу существующих.

## Таблица сравнения в README

Раздел «Сравнение форматов» (после «Как добавить формат вывода»). Строки — 9 форматов
+ Kreya + HTTPie; колонки: Секреты (env), Docs запроса, Docs папки,
Per-param description, Локальная папка (`--merge`), GUI/файловый импорт, CLI.

| Формат | Секреты | Docs запроса | Docs папки | Param description | Merge | Импорт | CLI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tree (Bruno) | ✓ | ✓ | ✓ | ✓ | ✓ | папка (Bruno) | — |
| bundled (OpenCollection) | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| postman v2.1 | ✓ | ✓ | ✓ | ✓ | — | GUI | — |
| postman-v3 (Native Git) | частично¹ | ✓ | ✓ | ✓ | ✓ | папка (Postman) | — |
| openapi | — | ✓ | — | ✓ | — | GUI/кодоген | — |
| yaak | частично² | ✓ | ✓ | —³ | ✓ | папка/`yaak import` | `yaak` CLI |
| insomnia v4 | ✓⁴ | ✓ | ✓ | ✓ | — | GUI | — |
| insomnia-v5 | частично | ✓ | ✓ | ✓ | ✓ | папка/git sync | `inso` |
| hoppscotch | ✓ | ✓ | ✓ | — | — | GUI | `hopp test` |
| Kreya | — | — | — | — | — | импорт Postman (наш `postman`) | — |
| HTTPie | — | — | — | — | — | — (нет формата коллекций у CLI) | сам CLI |

¹ accessToken в definition.yaml перегенерируется; ² флага нет, шифрование при
заполнении; ³ у form-строк Yaak нет description; ⁴ kvPairData `type: secret`
(финализируется эталонным тестом).

## Тесты

- Unit-маппинги каждого формата на фикстуре `COLLECTION` (структура ресурсов,
  конвертации плейсхолдеров, секреты, Bearer-наследование).
- E2E через `main()` для всех 4 (по образцу `TestCliPrintGolden` — full-line regex).
- Merge-e2e для yaak/insomnia-v5 (генерация → правка значения/токена → `--merge` →
  сохранение; `--prune` удаляет сироты).
- Контрактные тесты реестра: 9 форматов, merge-матрица
  `{tree, bundled, postman-v3, yaak, insomnia-v5}`, `matches` всех новых целей.
- Валидаторы: счётчики на выходе генерации.

## Ограничения и риски

- Два открытых деталь-вопроса (layout insomnia-v5; kvPairData/auth-объект v4)
  закрываются в первых задачах по исходникам Insomnia и фиксируются эталонными
  тестами — до коммита соответствующего формата.
- hoppscotch: включение выключенных параметров в body-строку — осознанное решение
  (пустые значения VK игнорирует).
- Форматы клиентов меняются (Hoppscotch v-поля, Yaak модели) — таблица сравнения
  фиксирует срез на 2026-09.

## Не входит

- Kreya: нативный экспорт не строится — путь через официальный импорт Postman
  (наш формат `postman`); отражено в таблице.
- HTTPie: у CLI нет формата коллекций; шпаргалка-скрипт и Desktop-схема отклонены.
- Изменения существующих 5 форматов, merge-правил, реестра-контракта
  (`FormatSpec` не расширяется).
