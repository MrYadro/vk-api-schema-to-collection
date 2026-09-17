#!/usr/bin/env python3
import argparse
import pathlib
import sys

from formats import FORMATS

SNIFF_PRIORITY = ("openapi", "hoppscotch", "postman", "postman-v3", "bundled", "tree")


def sniff_spec(path):
    for name in SNIFF_PRIORITY:
        spec = FORMATS[name]
        if spec.matches is not None and spec.matches(path):
            return spec
    return FORMATS["tree"]


def pick_format(path):
    spec = sniff_spec(path)
    if spec.name == "postman":
        name = pathlib.Path(path).name
        return "postman-environment" if "postman_environment" in name else "postman-collection"
    if spec.name in ("tree", "bundled"):
        return "opencollection"
    return spec.name


def main():
    parser = argparse.ArgumentParser(description="Validate a generated collection against its official JSON Schema")
    parser.add_argument("path", type=pathlib.Path, help="bundled .yaml, tree directory, or postman .json file")
    parser.add_argument("--schema", type=pathlib.Path, default=None, help="local schema override (opencollection)")
    args = parser.parse_args()
    spec = sniff_spec(args.path)
    if spec.name == "postman":
        name = args.path.name
        if "postman_environment" in name:
            res = spec.validate(args.path)
            if res is None:
                return None
            _, values = res
            print(f"OK: postman environment, {values} variables, 0 schema violations")
            return None
        folders, requests = spec.validate(args.path)
        print(f"OK: postman collection, {folders} folders, {requests} requests, 0 schema violations")
        return None
    if spec.name == "postman-v3":
        folders, requests = spec.validate(args.path)
        print(f"OK: postman v3 local, {folders} folders, {requests} requests, 0 structural violations")
        return None
    if spec.name == "openapi":
        paths, schemas = spec.validate(args.path)
        print(f"OK: openapi 3.1, {paths} paths, {schemas} schemas, 0 schema violations")
        return None
    if spec.name == "hoppscotch":
        folders, requests = spec.validate(args.path)
        print(f"OK: hoppscotch, {folders} folders, {requests} requests, 0 structural violations")
        return None
    folders, requests = spec.validate(args.path, args.schema)
    print(f"OK: {folders} folders, {requests} requests, 0 schema violations")
    return None


if __name__ == "__main__":
    sys.exit(main())
