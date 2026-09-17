import pathlib
import re

from core import require_yaml, to_yaml
from formats import FormatSpec, build_collection

VAR_PATTERN = re.compile(r"\{\{\s*([^{}\s][^{}]*?)\s*\}\}")

TYPE = "collection.insomnia.rest/5.0"
SCHEMA_VERSION = "5.1"
FILE_NAME = "insomnia.wrk_1.yaml"


def _var(value):
    return VAR_PATTERN.sub(r"{{ \1 }}", value)


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
            "sortKey": idx,
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
            "sortKey": folder_idx,
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
    matches=matches,
    validate=validate,
)
