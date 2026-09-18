import pathlib
import re
import shutil
import uuid

from core import require_yaml, to_yaml
from formats import FormatSpec, build_collection, postman
from merge_collection import _keep_index, _norm_name

POSTMAN_V3_KIND_COLLECTION = "collection"
POSTMAN_V3_KIND_REQUEST = "http-request"


def postman_v3_auth_id(info):
    return str(uuid.uuid5(postman.POSTMAN_NAMESPACE, f"v3-auth/{info.get('name', '')}/{info.get('version', '')}"))


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
                "code": postman.POSTMAN_TEST_SCRIPT,
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
        "color": postman.postman_hue(env.get("color") or "#0077FF"),
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


def matches(path):
    path = pathlib.Path(path)
    return path.is_dir() and (path / "postman" / "collections").is_dir()


def load_postman_v3(out_dir):
    out_dir = pathlib.Path(out_dir)
    root = out_dir / "postman"
    if not root.is_dir():
        return None
    yaml = require_yaml()
    items = []
    variables = []
    envs = []
    collections_dir = root / "collections"
    if collections_dir.is_dir():
        for coll_dir in sorted(collections_dir.iterdir()):
            if not coll_dir.is_dir():
                continue
            def_file = coll_dir / ".resources" / "definition.yaml"
            if def_file.is_file():
                doc = yaml.safe_load(def_file.read_text(encoding="utf-8")) or {}
                for name, value in (doc.get("variables") or {}).items():
                    variables.append({"name": name, "value": value})
            for d in sorted(coll_dir.iterdir()):
                if not d.is_dir() or d.name == ".resources":
                    continue
                requests = []
                for f in sorted(d.glob("*.request.yaml")):
                    doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                    rows = []
                    for row in ((doc.get("body") or {}).get("content") or []):
                        if not isinstance(row, dict):
                            continue
                        out_row = {"name": row.get("key") or "", "value": row.get("value") or ""}
                        if "disabled" in row:
                            out_row["disabled"] = row["disabled"]
                        if row.get("description"):
                            out_row["description"] = row["description"]
                        rows.append(out_row)
                    requests.append(
                        {
                            "info": {"name": f.name[: -len(".request.yaml")], "type": "http"},
                            "http": {"body": {"type": "form-urlencoded", "data": rows}},
                        }
                    )
                if requests:
                    items.append({"info": {"name": d.name, "type": "folder"}, "items": requests})
    env_dir = root / "environments"
    if env_dir.is_dir():
        for f in sorted(env_dir.glob("*.environment.yaml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            envs.append(
                {
                    "name": doc.get("name") or f.name[: -len(".environment.yaml")],
                    "variables": [
                        {"name": v.get("key") or "", "value": v.get("value") or ""}
                        for v in doc.get("values") or []
                        if isinstance(v, dict)
                    ],
                }
            )
    return {
        "info": {"name": "VK API"},
        "request": {"variables": variables},
        "config": {"environments": envs},
        "items": items,
    }


def v3_prune_orphans(out_path, collection):
    out_path = pathlib.Path(out_path)
    removed = []
    keep = _keep_index(collection)
    collections_dir = out_path / "postman" / "collections"
    if not collections_dir.is_dir():
        return removed
    for coll_dir in sorted(collections_dir.iterdir()):
        if not coll_dir.is_dir():
            continue
        for d in sorted(coll_dir.iterdir()):
            if not d.is_dir() or d.name == ".resources":
                continue
            keep_requests = keep.get(_norm_name(d.name))
            if keep_requests is None:
                shutil.rmtree(d)
                removed.append(d)
                continue
            for f in sorted(d.glob("*.request.yaml")):
                if _norm_name(f.name[: -len(".request.yaml")]) not in keep_requests:
                    f.unlink()
                    removed.append(f)
    return removed


def validate_postman_v3(root_dir):
    import yaml

    root_dir = pathlib.Path(root_dir)
    folders = requests = 0
    collections_dir = root_dir / "postman" / "collections"
    for collection_dir in collections_dir.iterdir():
        if not collection_dir.is_dir():
            continue
        definition_path = collection_dir / ".resources" / "definition.yaml"
        definition = yaml.safe_load(definition_path.read_text(encoding="utf-8"))
        if definition.get("$kind") != "collection":
            raise ValueError(f"unexpected $kind in {definition_path}")
        for path in collection_dir.rglob("*.yaml"):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            kind = doc.get("$kind") if isinstance(doc, dict) else None
            if path.name == "definition.yaml":
                if kind != "collection":
                    raise ValueError(f"unexpected $kind in {path}")
                if path.parent.parent != collection_dir:
                    folders += 1
            elif path.name.endswith(".request.yaml"):
                if kind != "http-request":
                    raise ValueError(f"unexpected $kind in {path}")
                if not isinstance(doc.get("url"), str) or not isinstance(doc.get("method"), str):
                    raise ValueError(f"missing url/method in {path}")
                requests += 1
    for env_file in (root_dir / "postman" / "environments").glob("*.yaml"):
        env = yaml.safe_load(env_file.read_text(encoding="utf-8"))
        if not env.get("name") or not isinstance(env.get("values"), list):
            raise ValueError(f"malformed environment {env_file}")
    return folders, requests


def validate(path, schema_override=None):
    return validate_postman_v3(path)


def _write(collection, out):
    return write_postman_v3(collection, out), ""


POSTMAN_V3_SPEC = FormatSpec(
    name="postman-v3",
    default_out="dist/postman/vk-api-local",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=_write,
    supports_merge=True,
    load_existing=load_postman_v3,
    prune_orphans=v3_prune_orphans,
    keep_old_items=False,
    matches=matches,
    validate=validate,
)
