import pathlib
import re

from core import require_yaml, to_yaml
from formats import FormatSpec, build_collection

TO_YAAK = re.compile(r"\{\{(\w+)\}\}")
FROM_YAAK = re.compile(r"\$\{\[\s*env\.(\w+)\s*\]\}")


def _yak(value):
    return TO_YAAK.sub(lambda m: "${[ env." + m.group(1) + " ]}", value)


def _unyak(value):
    return FROM_YAAK.sub(lambda m: "{{" + m.group(1) + "}}", value)


def _text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def yaak_resources(collection):
    resources = []
    auth = collection["request"]["auth"]
    resources.append(
        (
            "wrk_1",
            {
                "model": "workspace",
                "id": "wrk_1",
                "name": collection["info"]["name"],
                "description": collection.get("docs") or "",
                "authenticationType": "bearer",
                "authentication": {"token": _yak(auth["token"])},
            },
        )
    )
    for i, env in enumerate(collection.get("config", {}).get("environments", []), start=1):
        resources.append(
            (
                f"env_{i}",
                {
                    "model": "environment",
                    "id": f"env_{i}",
                    "name": env["name"],
                    "public": True,
                    "parentModel": "workspace",
                    "parentId": "wrk_1",
                    "variables": [{"name": v["name"], "value": v.get("value", ""), "enabled": True} for v in env.get("variables", [])],
                },
            )
        )
    rq = 0
    for i, folder in enumerate(collection.get("items", []), start=1):
        resources.append(
            (
                f"fl_{i}",
                {
                    "model": "folder",
                    "id": f"fl_{i}",
                    "workspaceId": "wrk_1",
                    "folderId": None,
                    "name": folder["info"]["name"],
                    "description": folder.get("docs") or folder["info"].get("description") or "",
                },
            )
        )
        for j, req in enumerate(folder.get("items", []), start=1):
            rq += 1
            http = req.get("http", {})
            resources.append(
                (
                    f"rq_{rq}",
                    {
                        "model": "http_request",
                        "id": f"rq_{rq}",
                        "workspaceId": "wrk_1",
                        "folderId": f"fl_{i}",
                        "name": req["info"]["name"],
                        "method": http.get("method", "POST"),
                        "url": _yak(http.get("url", "")),
                        "bodyType": "application/x-www-form-urlencoded",
                        "body": {
                            "form": [
                                {"name": r["name"], "value": _yak(r.get("value", "")), "enabled": not r.get("disabled")}
                                for r in http.get("body", {}).get("data", [])
                            ]
                        },
                        "description": req.get("docs") or req["info"].get("description") or "",
                    },
                )
            )
    return resources


def write_yaak(collection, out):
    out.mkdir(parents=True, exist_ok=True)
    resources = yaak_resources(collection)
    for rid, doc in resources:
        (out / f"yaak.{rid}.yaml").write_text(to_yaml(doc), encoding="utf-8")
    return len(resources), ""


def load_yaak(out):
    out = pathlib.Path(out)
    files = sorted(out.glob("yaak.*.yaml"))
    if not files:
        return None
    yaml = require_yaml()
    docs = [d for d in (yaml.safe_load(f.read_text(encoding="utf-8")) for f in files) if isinstance(d, dict)]
    workspace = next((d for d in docs if d.get("model") == "workspace"), None)
    if workspace is None:
        return None
    folders = [d for d in docs if d.get("model") == "folder"]
    requests = [d for d in docs if d.get("model") == "http_request"]
    items = []
    for folder in sorted(folders, key=lambda d: d.get("id", "")):
        children = [r for r in requests if r.get("folderId") == folder.get("id")]
        items.append(
            {
                "info": {"name": _text(folder.get("name")), "type": "folder", "description": folder.get("description")},
                "request": {"auth": "inherit"},
                "items": [
                    {
                        "info": {"name": _text(r.get("name")), "type": "http", "description": r.get("description")},
                        "http": {
                            "method": r.get("method", "POST"),
                            "url": _unyak(_text(r.get("url"))),
                            "auth": "inherit",
                            "body": {
                                "type": "form-urlencoded",
                                "data": [
                                    {"name": p["name"], "value": _unyak(_text(p.get("value"))), **({"disabled": True} if not p.get("enabled", True) else {})}
                                    for p in (r.get("body") or {}).get("form", [])
                                ],
                            },
                        },
                        "docs": r.get("description"),
                    }
                    for r in children
                ],
                "docs": folder.get("description"),
            }
        )
    envs = []
    for env in [d for d in docs if d.get("model") == "environment"]:
        envs.append(
            {
                "name": _text(env.get("name")),
                "variables": [{"name": v["name"], "value": _text(v.get("value"))} for v in env.get("variables", [])],
            }
        )
    return {
        "opencollection": "1.0.0",
        "info": {"name": _text(workspace.get("name")), "description": workspace.get("description", "")},
        "request": {"auth": {"type": "bearer", "token": _unyak(_text((workspace.get("authentication") or {}).get("token")))}},
        "config": {"environments": envs},
        "items": items,
        "docs": workspace.get("description", ""),
    }


def yaak_prune_orphans(out, collection):
    out = pathlib.Path(out)
    keep = {rid for rid, _ in yaak_resources(collection)}
    removed = []
    for f in sorted(out.glob("yaak.*.yaml")):
        rid = f.name[len("yaak.") : -len(".yaml")]
        if rid not in keep:
            f.unlink()
            removed.append(f)
    return removed


def matches(path):
    path = pathlib.Path(path)
    return path.is_dir() and any(path.glob("yaak.*.yaml"))


def validate(path, schema_override=None):
    yaml = require_yaml()
    docs = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted(pathlib.Path(path).glob("yaak.*.yaml"))]
    models = [d.get("model") for d in docs if isinstance(d, dict)]
    if any(m not in ("workspace", "environment", "folder", "http_request") for m in models):
        raise ValueError(f"unexpected yaak models in {path}")
    return models.count("folder"), models.count("http_request")


YAAK_SPEC = FormatSpec(
    name="yaak",
    default_out="dist/yaak/vk-api",
    stats_keys=("folders", "requests"),
    model_based=True,
    build=build_collection,
    write=write_yaak,
    supports_merge=True,
    load_existing=load_yaak,
    prune_orphans=yaak_prune_orphans,
    keep_old_items=True,
    matches=matches,
    validate=validate,
)
