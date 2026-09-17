import pathlib
import re
import shutil

import core
from core import SAFE_FILENAME, jsonschema_validator, load_document, require_yaml, to_yaml
from formats import FormatSpec, build_collection
from merge_collection import _keep_index, _norm_name

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


def write_bundled(collection, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_yaml({**collection, "bundled": True}), encoding="utf-8")
    return 1, ""


def load_bundled(path):
    path = pathlib.Path(path)
    if not path.is_file():
        return None
    doc = require_yaml().safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return None
    doc.pop("bundled", None)
    return doc


def load_tree(out_dir):
    out_dir = pathlib.Path(out_dir)
    root_file = out_dir / "opencollection.yml"
    if not root_file.is_file():
        return None
    yaml = require_yaml()
    collection = yaml.safe_load(root_file.read_text(encoding="utf-8"))
    if not isinstance(collection, dict):
        return None
    env_dir = out_dir / "environments"
    envs = []
    if env_dir.is_dir():
        for f in sorted(env_dir.glob("*.yml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                envs.append(doc)
    collection["config"] = {"environments": envs}
    folders = []
    for d in sorted(p for p in out_dir.iterdir() if p.is_dir() and p.name != "environments"):
        folder_doc = {"info": {"name": d.name, "type": "folder"}}
        folder_file = d / "folder.yml"
        if folder_file.is_file():
            doc = yaml.safe_load(folder_file.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                folder_doc = doc
        requests = []
        for f in sorted(d.glob("*.yml")):
            if f.name == "folder.yml":
                continue
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and isinstance(doc.get("info"), dict):
                requests.append(doc)
        requests.sort(key=lambda r: r["info"].get("seq") or 0)
        folder_doc["items"] = requests
        folders.append(folder_doc)
    folders.sort(key=lambda f: (f.get("info") or {}).get("seq") or 0)
    collection["items"] = folders
    return collection


def tree_prune_orphans(out_path, collection):
    out_path = pathlib.Path(out_path)
    removed = []
    keep = _keep_index(collection)
    if not out_path.is_dir():
        return removed
    yaml = require_yaml()
    for d in sorted(p for p in out_path.iterdir() if p.is_dir() and p.name != "environments"):
        folder_name = _norm_name(d.name)
        folder_file = d / "folder.yml"
        if folder_file.is_file():
            doc = yaml.safe_load(folder_file.read_text(encoding="utf-8")) or {}
            folder_name = _norm_name((doc.get("info") or {}).get("name") or d.name)
        keep_requests = keep.get(folder_name)
        if keep_requests is None:
            shutil.rmtree(d)
            removed.append(d)
            continue
        for f in sorted(d.glob("*.yml")):
            if f.name == "folder.yml":
                continue
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            req_name = _norm_name((doc.get("info") or {}).get("name") or f.stem)
            if req_name not in keep_requests:
                f.unlink()
                removed.append(f)
    return removed


def bundled_prune_orphans(out_path, collection):
    return []


def _tree_write(collection, out):
    return write_tree(collection, out), ""


def _bundled_write(collection, out):
    return write_bundled(collection, out)


def matches_tree(path):
    path = pathlib.Path(path)
    return path.is_dir() and not (path / "postman" / "collections").is_dir()


def matches_bundled(path):
    path = pathlib.Path(path)
    return not path.is_dir() and path.suffix in (".yaml", ".yml")


def validate_bundled(doc_path, schema):
    doc = load_document(doc_path)
    jsonschema_validator(schema).validate(doc)
    folders = [i for i in doc.get("items", []) if isinstance(i, dict)]
    requests = [r for f in folders for r in f.get("items", [])]
    return len(folders), len(requests)


def validate_tree(root_dir, schema):
    import yaml
    from jsonschema import Draft7Validator

    root_dir = pathlib.Path(root_dir)
    defs = schema["$defs"]
    checks = {
        "Folder": Draft7Validator({"$ref": "#/$defs/Folder", "$defs": defs}),
        "HttpRequest": Draft7Validator({"$ref": "#/$defs/HttpRequest", "$defs": defs}),
        "Environment": Draft7Validator({"$ref": "#/$defs/Environment", "$defs": defs}),
    }
    Draft7Validator(schema).validate(
        yaml.safe_load((root_dir / "opencollection.yml").read_text(encoding="utf-8"))
    )
    for env in (root_dir / "environments").glob("*.yml"):
        checks["Environment"].validate(yaml.safe_load(env.read_text(encoding="utf-8")))
    folders = requests = 0
    for folder_dir in sorted(p for p in root_dir.iterdir() if p.is_dir() and p.name != "environments"):
        checks["Folder"].validate(yaml.safe_load((folder_dir / "folder.yml").read_text(encoding="utf-8")))
        folders += 1
        for req_file in folder_dir.glob("*.yml"):
            if req_file.name == "folder.yml":
                continue
            checks["HttpRequest"].validate(yaml.safe_load(req_file.read_text(encoding="utf-8")))
            requests += 1
    return folders, requests


def _validate_tree(path, schema_override=None):
    return validate_tree(path, core.load_schema(schema_override, core.OC_SCHEMA_URL))


def _validate_bundled(path, schema_override=None):
    return validate_bundled(path, core.load_schema(schema_override, core.OC_SCHEMA_URL))


TREE_SPEC = FormatSpec(
    name="tree",
    default_out="dist/opencollection/vk-api",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=_tree_write,
    supports_merge=True,
    load_existing=load_tree,
    prune_orphans=tree_prune_orphans,
    matches=matches_tree,
    validate=_validate_tree,
)
BUNDLED_SPEC = FormatSpec(
    name="bundled",
    default_out="dist/opencollection/vk-api.yaml",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=_bundled_write,
    supports_merge=True,
    load_existing=load_bundled,
    prune_orphans=bundled_prune_orphans,
    matches=matches_bundled,
    validate=_validate_bundled,
)
