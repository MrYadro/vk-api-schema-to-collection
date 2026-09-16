#!/usr/bin/env python3
import argparse
import json
import pathlib
import sys

OC_SCHEMA_URL = "https://schema.opencollection.com/opencollection/v1.0.0.json"
POSTMAN_COLLECTION_SCHEMA_URL = "https://schema.postman.com/collection/json/v2.1.0/draft-07/collection.json"
POSTMAN_ENVIRONMENT_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/environment.json"
OPENAPI_SCHEMA_URL = "https://spec.openapis.org/oas/3.1/schema/2022-10-07"


def pick_format(path):
    path = pathlib.Path(path)
    name = path.name
    if name.endswith(".openapi.yaml") or path.parent.name == "openapi":
        return "openapi"
    if "postman_collection" in name and name.endswith(".json"):
        return "postman-collection"
    if "postman_environment" in name and name.endswith(".json"):
        return "postman-environment"
    return "opencollection"


def load_schema(path, url):
    if path:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_document(path):
    path = pathlib.Path(path)
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def jsonschema_validator(schema):
    from jsonschema.validators import validator_for

    return validator_for(schema)(schema)


def allow_postman_secret_type(schema):
    variable = schema.get("definitions", {}).get("variable") or schema.get("$defs", {}).get("variable")
    if variable:
        enum = variable.get("properties", {}).get("type", {}).get("enum")
        if enum and "secret" not in enum:
            enum.append("secret")
    return schema


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


def validate_postman_collection(doc_path, schema):
    doc = load_document(doc_path)
    jsonschema_validator(schema).validate(doc)
    folders = 0
    requests = 0

    def walk(items):
        nonlocal folders, requests
        for item in items:
            if "item" in item:
                folders += 1
                walk(item["item"])
            elif "request" in item:
                requests += 1

    walk(doc.get("item", []))
    return folders, requests


def validate_postman_environment(doc_path, schema):
    doc = load_document(doc_path)
    jsonschema_validator(schema).validate(doc)
    return 0, len(doc.get("values", []))


def validate_openapi(doc_path, schema):
    doc = load_document(doc_path)
    jsonschema_validator(schema).validate(doc)
    return len(doc.get("paths", {})), len(doc.get("components", {}).get("schemas", {}))


def main():
    parser = argparse.ArgumentParser(description="Validate a generated collection against its official JSON Schema")
    parser.add_argument("path", type=pathlib.Path, help="bundled .yaml, tree directory, or postman .json file")
    parser.add_argument("--schema", type=pathlib.Path, default=None, help="local schema override (opencollection)")
    args = parser.parse_args()

    fmt = pick_format(args.path)
    if fmt == "openapi":
        schema = load_schema(None, OPENAPI_SCHEMA_URL)
        paths, schemas = validate_openapi(args.path, schema)
        print(f"OK: openapi 3.1, {paths} paths, {schemas} schemas, 0 schema violations")
    elif fmt == "postman-collection":
        schema = allow_postman_secret_type(load_schema(None, POSTMAN_COLLECTION_SCHEMA_URL))
        folders, requests = validate_postman_collection(args.path, schema)
        print(f"OK: postman collection, {folders} folders, {requests} requests, 0 schema violations")
    elif fmt == "postman-environment":
        try:
            schema = load_schema(None, POSTMAN_ENVIRONMENT_SCHEMA_URL)
        except OSError:
            print(f"SKIP: postman environment schema unavailable online ({POSTMAN_ENVIRONMENT_SCHEMA_URL}), validation skipped")
            return None
        _, values = validate_postman_environment(args.path, schema)
        print(f"OK: postman environment, {values} variables, 0 schema violations")
    elif args.path.is_dir():
        folders, requests = validate_tree(args.path, load_schema(args.schema, OC_SCHEMA_URL))
        print(f"OK: {folders} folders, {requests} requests, 0 schema violations")
    else:
        folders, requests = validate_bundled(args.path, load_schema(args.schema, OC_SCHEMA_URL))
        print(f"OK: {folders} folders, {requests} requests, 0 schema violations")


if __name__ == "__main__":
    sys.exit(main())
