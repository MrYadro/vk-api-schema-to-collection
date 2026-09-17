import copy
import pathlib
import re
import shutil

V3_UNSAFE = re.compile(r"[/\\:]")


def _require_yaml():
    try:
        import yaml
    except ImportError:
        raise SystemExit("--merge/--prune need PyYAML: pip install pyyaml")
    return yaml


def load_bundled(path):
    path = pathlib.Path(path)
    if not path.is_file():
        return None
    doc = _require_yaml().safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return None
    doc.pop("bundled", None)
    return doc


def load_tree(out_dir):
    out_dir = pathlib.Path(out_dir)
    root_file = out_dir / "opencollection.yml"
    if not root_file.is_file():
        return None
    yaml = _require_yaml()
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


def load_postman_v3(out_dir):
    out_dir = pathlib.Path(out_dir)
    root = out_dir / "postman"
    if not root.is_dir():
        return None
    yaml = _require_yaml()
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


def load_existing(out_path, fmt):
    if fmt == "bundled":
        return load_bundled(out_path)
    if fmt == "tree":
        return load_tree(out_path)
    if fmt == "postman-v3":
        return load_postman_v3(out_path)
    return None


def _norm_name(name):
    return V3_UNSAFE.sub("_", name or "")


def _keep_index(collection):
    keep = {}
    for folder in collection.get("items") or []:
        key = _norm_name((folder.get("info") or {}).get("name"))
        keep[key] = {_norm_name((r.get("info") or {}).get("name")) for r in folder.get("items") or []}
    return keep


def prune_orphans(out_path, fmt, collection):
    out_path = pathlib.Path(out_path)
    removed = []
    keep = _keep_index(collection)
    if fmt == "tree":
        if not out_path.is_dir():
            return removed
        yaml = _require_yaml()
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
    elif fmt == "postman-v3":
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


def merge(new, old, prune=False, keep_old_items=True):
    merged = copy.deepcopy(new)
    old = copy.deepcopy(old)
    stats = {
        "added": 0,
        "updated": 0,
        "kept": 0,
        "pruned": 0,
        "preserved_values": 0,
        "preserved_disabled": 0,
    }
    _merge_variables(
        (merged.get("request") or {}).get("variables") or [],
        (old.get("request") or {}).get("variables") or [],
        stats,
    )
    old_envs = {(e.get("name") or ""): e for e in (old.get("config") or {}).get("environments") or []}
    for env in (merged.get("config") or {}).get("environments") or []:
        old_env = old_envs.get(env.get("name") or "")
        if old_env is not None:
            _merge_variables(env.get("variables") or [], old_env.get("variables") or [], stats)
    old_folders = {}
    for f in old.get("items") or []:
        old_folders[_norm_name((f.get("info") or {}).get("name"))] = f
    items = merged.get("items") or []
    if items:
        old_head = old_folders.pop(_norm_name((items[0].get("info") or {}).get("name")), None)
        if old_head is not None:
            _merge_folder(items[0], old_head, stats, prune, keep_old_items, sort_items=False)
    rest = items[1:]
    for folder in rest:
        old_folder = old_folders.pop(_norm_name((folder.get("info") or {}).get("name")), None)
        if old_folder is None:
            stats["added"] += 1 + len(folder.get("items") or [])
        else:
            _merge_folder(folder, old_folder, stats, prune, keep_old_items)
    for old_folder in old_folders.values():
        count = 1 + len(old_folder.get("items") or [])
        if prune:
            stats["pruned"] += count
        else:
            stats["kept"] += count
            if keep_old_items:
                rest.append(old_folder)
    rest.sort(key=lambda f: (f.get("info") or {}).get("name") or "")
    items = ([items[0]] if items else []) + rest
    merged["items"] = items
    for i, folder in enumerate(items):
        folder.setdefault("info", {})["seq"] = i + 1
        for j, req in enumerate(folder.get("items") or []):
            req.setdefault("info", {})["seq"] = j + 1
    for k, v in old.items():
        if k not in merged:
            merged[k] = copy.deepcopy(v)
    return merged, stats


def _protect_slots(new_row, old_row, stats):
    if old_row.get("value", "") != new_row.get("value", ""):
        new_row["value"] = old_row.get("value", "")
        stats["preserved_values"] += 1
    old_disabled = bool(old_row.get("disabled", False))
    new_disabled = bool(new_row.get("disabled", False))
    if old_disabled != new_disabled:
        if old_disabled:
            new_row["disabled"] = True
        else:
            new_row.pop("disabled", None)
        stats["preserved_disabled"] += 1


def _merge_rows(new_rows, old_rows, stats):
    old_by_name = {}
    for row in old_rows:
        old_by_name.setdefault(row.get("name") or "", []).append(row)
    used = set()
    out = []
    for nr in new_rows:
        group = old_by_name.get(nr.get("name") or "", [])
        available = [r for r in group if id(r) not in used]
        match = None
        if len(group) == 1 and len(available) == 1:
            match = available[0]
        else:
            for r in available:
                if (r.get("value") or "") == (nr.get("value") or ""):
                    match = r
                    break
        if match is not None:
            used.add(id(match))
            _protect_slots(nr, match, stats)
        out.append(nr)
    v_index = len(out)
    for i, nr in enumerate(out):
        if nr.get("name") == "v":
            v_index = i
            break
    out[v_index:v_index] = [r for r in old_rows if id(r) not in used]
    return out


def _merge_request(req, old_req, stats):
    body = (req.get("http") or {}).get("body") or {}
    old_body = (old_req.get("http") or {}).get("body") or {}
    if isinstance(body.get("data"), list) and isinstance(old_body.get("data"), list):
        body["data"] = _merge_rows(body["data"], old_body["data"], stats)
    for k, v in old_req.get("http", {}).items():
        if k != "body" and k not in req["http"]:
            req["http"][k] = copy.deepcopy(v)


def _merge_folder(folder, old_folder, stats, prune, keep_old_items, sort_items=True):
    old_requests = {}
    for r in old_folder.get("items") or []:
        old_requests[_norm_name((r.get("info") or {}).get("name"))] = r
    out = []
    for req in folder.get("items") or []:
        old_req = old_requests.pop(_norm_name((req.get("info") or {}).get("name")), None)
        if old_req is None:
            stats["added"] += 1
        else:
            stats["updated"] += 1
            _merge_request(req, old_req, stats)
            for k, v in old_req.items():
                if k not in req:
                    req[k] = copy.deepcopy(v)
        out.append(req)
    for old_req in old_requests.values():
        if prune:
            stats["pruned"] += 1
        else:
            stats["kept"] += 1
            if keep_old_items:
                out.append(old_req)
    folder["items"] = out
    if sort_items:
        folder["items"].sort(key=lambda r: _norm_name((r.get("info") or {}).get("name")))
    for k, v in old_folder.items():
        if k != "items" and k not in folder:
            folder[k] = copy.deepcopy(v)


def _merge_variables(new_vars, old_vars, stats):
    old_by_name = {v.get("name") or "": v for v in old_vars}
    present = set()
    for var in new_vars:
        name = var.get("name") or ""
        present.add(name)
        old_var = old_by_name.get(name)
        if old_var is None or name == "apiVersion":
            continue
        if old_var.get("value", "") != var.get("value", ""):
            var["value"] = old_var.get("value", "")
            stats["preserved_values"] += 1
    for name, old_var in old_by_name.items():
        if name and name not in present:
            new_vars.append(copy.deepcopy(old_var))
