#!/usr/bin/env python3
import argparse
import json
import pathlib
import sys

import yaml
from jsonschema import Draft7Validator

OC_SCHEMA_URL = "https://schema.opencollection.com/opencollection/v1.0.0.json"


def load_schema(path):
    if path:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    import urllib.request

    with urllib.request.urlopen(OC_SCHEMA_URL, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def validate_bundled(doc_path, schema):
    doc = yaml.safe_load(pathlib.Path(doc_path).read_text(encoding="utf-8"))
    Draft7Validator(schema).validate(doc)
    folders = [i for i in doc.get("items", []) if isinstance(i, dict)]
    requests = [r for f in folders for r in f.get("items", [])]
    return len(folders), len(requests)


def validate_tree(root_dir, schema):
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


def main():
    parser = argparse.ArgumentParser(description="Validate an OpenCollection against the official JSON Schema")
    parser.add_argument("path", type=pathlib.Path, help="bundled .yaml file or tree directory")
    parser.add_argument("--schema", type=pathlib.Path, default=None, help="local opencollection schema (default: fetched from spec)")
    args = parser.parse_args()

    schema = load_schema(args.schema)
    if args.path.is_dir():
        folders, requests = validate_tree(args.path, schema)
    else:
        folders, requests = validate_bundled(args.path, schema)
    print(f"OK: {folders} folders, {requests} requests, 0 schema violations")


if __name__ == "__main__":
    sys.exit(main())
