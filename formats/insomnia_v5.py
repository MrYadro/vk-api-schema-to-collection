import pathlib
import re

from core import require_yaml, to_yaml
from formats import FormatSpec, build_collection
from formats import insomnia

VAR_PATTERN = re.compile(r"\{\{\s*([^{}\s][^{}]*?)\s*\}\}")

TYPE = "collection.insomnia.rest/5.0"
SCHEMA_VERSION = "5.1"
FILE_NAME = "insomnia.wrk_1.yaml"


def _var(value):
    return VAR_PATTERN.sub(r"{{ \1 }}", value)


def _unvar(value):
    return VAR_PATTERN.sub(r"{{\1}}", value)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _params(rows):
    out = []
    for r in rows:
        param = {"name": r["name"], "value": _var(r.get("value", ""))}
        if r.get("description"):
            param["description"] = r["description"]
        if r.get("disabled"):
            param["disabled"] = True
        out.append(param)
    return out


def _v5_request(req, folder_idx, idx):
    http = req["http"]
    return {
        "name": req["info"]["name"],
        "meta": {
            "id": f"__REQ_{folder_idx}_{idx}__",
            "description": req.get("docs") or req["info"].get("description") or "",
            "sortKey": idx * 1000,
        },
        "method": http["method"],
        "url": _var(http["url"]),
        "body": {
            "mimeType": "application/x-www-form-urlencoded",
            "params": _params(http.get("body", {}).get("data", [])),
        },
    }


def _v5_folder(folder, folder_idx):
    return {
        "name": folder["info"]["name"],
        "meta": {
            "id": f"__GRP_{folder_idx}__",
            "description": folder.get("docs") or folder["info"].get("description") or "",
            "sortKey": folder_idx * 1000,
        },
        "children": [
            _v5_request(req, folder_idx, idx)
            for idx, req in enumerate(folder.get("items", []), start=1)
        ],
    }


def _v5_environments(collection):
    subs = []
    for i, env in enumerate(collection.get("config", {}).get("environments", []), start=1):
        variables = env.get("variables", [])
        sub = {
            "name": env["name"],
            "meta": {"id": f"__ENV_{i + 1}__", "sortKey": i},
            "data": {v["name"]: v.get("value", "") for v in variables},
        }
        names = [v["name"] for v in variables]
        if names:
            sub["dataPropertyOrder"] = {"&": names}
        if env.get("color"):
            sub["color"] = env["color"]
        subs.append(sub)
    return {"name": "Base Environment", "meta": {"id": "__ENV_1__"}, "subEnvironments": subs}


def to_insomnia_v5(collection):
    root = {
        "name": collection["info"]["name"],
        "meta": {"id": "__GRP_0__", "description": collection.get("docs") or "", "sortKey": 0},
        "scripts": {"afterResponse": insomnia.INSOMNIA_TEST_SCRIPT},
        "authentication": {
            "type": "bearer",
            "token": _var(collection["request"]["auth"]["token"]),
            "prefix": "",
        },
        "children": [
            _v5_folder(folder, i)
            for i, folder in enumerate(collection.get("items", []), start=1)
        ],
    }
    return {
        "type": TYPE,
        "schema_version": SCHEMA_VERSION,
        "name": collection["info"]["name"],
        "meta": {"id": "__WORKSPACE_ID__"},
        "collection": [root],
        "environments": _v5_environments(collection),
        "cookieJar": {"name": "Default Cookie Jar", "meta": {"id": "__COOKIE_JAR_1__"}},
    }


def write_insomnia_v5(collection, out):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / FILE_NAME).write_text(to_yaml(to_insomnia_v5(collection)), encoding="utf-8")
    return 1, ""


def _load_rows(params):
    rows = []
    for p in params or []:
        if not isinstance(p, dict):
            continue
        row = {"name": _text(p.get("name")), "value": _unvar(_text(p.get("value")))}
        if p.get("description"):
            row["description"] = p["description"]
        if p.get("disabled"):
            row["disabled"] = True
        rows.append(row)
    return rows


def _load_request(req):
    meta = req.get("meta") or {}
    info = {"name": _text(req.get("name")), "type": "http"}
    if meta.get("description"):
        info["description"] = meta["description"]
    body = req.get("body") or {}
    return {
        "info": info,
        "http": {
            "method": req.get("method") or "POST",
            "url": _unvar(_text(req.get("url"))),
            "auth": "inherit",
            "body": {"type": "form-urlencoded", "data": _load_rows(body.get("params"))},
        },
        "docs": meta.get("description") or "",
    }


def _load_folder(folder):
    meta = folder.get("meta") or {}
    info = {"name": _text(folder.get("name")), "type": "folder"}
    if meta.get("description"):
        info["description"] = meta["description"]
    return {
        "info": info,
        "request": {"auth": "inherit"},
        "items": [
            _load_request(child)
            for child in folder.get("children") or []
            if isinstance(child, dict) and "method" in child
        ],
        "docs": meta.get("description") or "",
    }


def _load_env_variables(node):
    data = node.get("data") or {}
    order = (node.get("dataPropertyOrder") or {}).get("&") or []
    ordered = [k for k in order if isinstance(k, str) and k in data]
    ordered += [k for k in data if k not in set(ordered)]
    return [{"name": k, "value": _text(data.get(k))} for k in ordered]


def _load_environments(envs):
    environments = []
    for sub in envs.get("subEnvironments") or []:
        if not isinstance(sub, dict):
            continue
        env = {"name": _text(sub.get("name")), "variables": _load_env_variables(sub)}
        if sub.get("color"):
            env["color"] = sub["color"]
        environments.append(env)
    if envs.get("data"):
        environments.append(
            {"name": envs.get("name") or "Base Environment", "variables": _load_env_variables(envs)}
        )
    return environments


def load_insomnia_v5(out):
    out = pathlib.Path(out)
    files = sorted(f for f in out.glob("insomnia.*.yaml") if f.is_file())
    if not files:
        return None
    docs = []
    for f in files:
        doc = require_yaml().safe_load(f.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("type") == TYPE and isinstance(doc.get("collection"), list) and doc["collection"]:
            docs.append(doc)
    if not docs:
        return None
    root = docs[0]["collection"][0]
    if not isinstance(root, dict):
        return None
    items = []
    for doc in docs:
        nodes = [n for n in doc["collection"] if isinstance(n, dict)]
        groups = nodes[0].get("children") or [] if len(nodes) == 1 else nodes[1:]
        items.extend(_load_folder(g) for g in groups if isinstance(g, dict) and "method" not in g)
    meta = root.get("meta") or {}
    auth = root.get("authentication") or {}
    envs_doc = next((d.get("environments") for d in docs if isinstance(d.get("environments"), dict)), {})
    return {
        "opencollection": "1.0.0",
        "info": {"name": _text(root.get("name"))},
        "request": {"auth": {"type": auth.get("type") or "bearer", "token": _unvar(_text(auth.get("token")))}},
        "config": {"environments": _load_environments(envs_doc)},
        "items": items,
        "docs": meta.get("description") or "",
    }


def insomnia_v5_prune_orphans(out, collection):
    out = pathlib.Path(out)
    keep = out / FILE_NAME
    removed = []
    for f in sorted(out.rglob("*.yaml")):
        if not f.is_file() or f == keep:
            continue
        with f.open(encoding="utf-8") as fh:
            if TYPE not in fh.readline():
                continue
        f.unlink()
        removed.append(f)
    return removed


def matches(path):
    path = pathlib.Path(path)
    if not path.is_dir():
        return False
    for f in sorted(path.glob("insomnia.*.yaml")):
        if f.is_file() and TYPE in f.open(encoding="utf-8").readline():
            return True
    return False


def _tree_counts(items):
    items = [i for i in (items or []) if isinstance(i, dict)]
    if len(items) == 1 and "method" not in items[0]:
        items = [i for i in (items[0].get("children") or []) if isinstance(i, dict)]
    folders = requests = 0
    stack = list(items)
    while stack:
        item = stack.pop()
        if "method" in item:
            requests += 1
        else:
            folders += 1
            stack.extend(i for i in (item.get("children") or []) if isinstance(i, dict))
    return folders, requests


def validate(path, schema_override=None):
    yaml = require_yaml()
    files = sorted(pathlib.Path(path).glob("insomnia.*.yaml"))
    if not files:
        raise ValueError(f"not an insomnia v5 git-sync folder: {path}")
    folders = requests = 0
    for f in files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("type") != TYPE:
            raise ValueError(f"not an insomnia v5 collection: {f}")
        f_count, r_count = _tree_counts(doc.get("collection"))
        folders += f_count
        requests += r_count
    return folders, requests


INSOMNIA_V5_SPEC = FormatSpec(
    name="insomnia-v5",
    default_out="dist/insomnia/vk-api-local",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_insomnia_v5,
    supports_merge=True,
    load_existing=load_insomnia_v5,
    prune_orphans=insomnia_v5_prune_orphans,
    keep_old_items=True,
    matches=matches,
    validate=validate,
)
