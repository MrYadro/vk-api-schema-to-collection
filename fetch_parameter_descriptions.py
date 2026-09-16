#!/usr/bin/env python3
import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from generate_collection import collect_methods

API_URL = "https://api.vk.ru/method/documentation.getPage"
ANON_TOKEN_URL = "https://dev.vk.ru/getAnonymousToken"


def get_anonymous_token(timeout=30):
    with urllib.request.urlopen(ANON_TOKEN_URL, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["response"]["token"]


def extract_descriptions(payload):
    page = (payload.get("response") or {}).get("page") or {}
    contents = page.get("contents") or {}
    entry = {
        "description": contents.get("description") or contents.get("short_description") or "",
        "params_common_description": contents.get("params_common_description") or "",
        "params": {},
    }
    for p in contents.get("params") or []:
        name = p.get("name")
        if name:
            entry["params"][name] = p.get("description") or ""
    return entry


def call(name, token, api_version, timeout):
    form = urllib.parse.urlencode(
        {
            "page": f"method/{name}",
            "lang": "ru",
            "v": api_version,
            "access_token": token,
        }
    ).encode()
    req = urllib.request.Request(API_URL, data=form, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Fetch VK dev portal method parameter descriptions")
    parser.add_argument("--schema-dir", default=None, type=pathlib.Path)
    parser.add_argument("--out", default=pathlib.Path(__file__).resolve().parent / "data/parameter_descriptions.json", type=pathlib.Path)
    parser.add_argument("--token-file", default=pathlib.Path("/var/folders/0b/6qw3z1n13pb32w2dds02p7l80000gp/T/opencode/vk_token"), type=pathlib.Path)
    parser.add_argument("--use-file-token", action="store_true", help="force token from --token-file instead of anonymous dev portal token")
    parser.add_argument("--api-version", default="5.190")
    parser.add_argument("--rps", type=float, default=3.0)
    parser.add_argument("--limit", type=int, default=0, help="fetch only first N missing methods (0 = all)")
    parser.add_argument("--save-every", type=int, default=50)
    parser.add_argument("--method", default=None, help="single method name for testing")
    parser.add_argument("--all", action="store_true", help="fetch all methods including nodoc/hidden (default: public only)")
    args = parser.parse_args()
    if args.schema_dir is None:
        from generate_collection import default_schema_dir

        args.schema_dir = default_schema_dir()

    token = ""
    if args.use_file_token and args.token_file.exists():
        token = args.token_file.read_text(encoding="utf-8").strip()
        print("using token from file", flush=True)
    if not token:
        token = get_anonymous_token()
        print("using anonymous dev portal token", flush=True)
    if not token:
        sys.exit("empty token")

    cache = {}
    if args.out.exists():
        cache = json.loads(args.out.read_text(encoding="utf-8"))

    if args.method:
        payload = call(args.method, token, args.api_version, 30)
        entry = extract_descriptions(payload) if payload.get("response", {}).get("code") == 200 else payload
        print(json.dumps(entry, ensure_ascii=False, indent=1)[:3000])
        return

    methods, _, _ = collect_methods(args.schema_dir)
    methods = {
        name: entry
        for name, entry in methods.items()
        if args.all
        or (
            entry[0].get("nodoc") is not True
            and (entry[0].get("meta") or {}).get("hidden") is not True
        )
    }
    todo = [n for n in sorted(methods) if n not in cache]
    if args.limit:
        todo = todo[: args.limit]
    print(f"total={len(methods)} cached={len(cache)} todo={len(todo)}", flush=True)

    delay = 1.0 / args.rps
    fetched = errors = 0
    started = time.monotonic()
    for i, name in enumerate(todo):
        for attempt in range(5):
            try:
                payload = call(name, token, args.api_version, 30)
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                if attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise
        if "error" in payload:
            code = payload["error"].get("error_code")
            if code == 5 and not args.use_file_token:
                token = get_anonymous_token()
                try:
                    payload = call(name, token, args.api_version, 30)
                except (urllib.error.URLError, TimeoutError):
                    payload = {"error": {"error_code": 0}}
                if payload.get("response", {}).get("code") == 200:
                    cache[name] = extract_descriptions(payload)
                    fetched += 1
                    time.sleep(delay)
                    continue
            if code in (5, 6, 9, 10):
                time.sleep(1.0)
                continue
            cache[name] = {"missing": True, "error_code": code}
            errors += 1
        elif payload.get("response", {}).get("code") != 200:
            cache[name] = {"missing": True}
            errors += 1
        else:
            cache[name] = extract_descriptions(payload)
            fetched += 1
        if (i + 1) % args.save_every == 0 or i == len(todo) - 1:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.out.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(args.out)
            done = i + 1
            rate = done / max(time.monotonic() - started, 0.001)
            print(
                f"{done}/{len(todo)} fetched={fetched} errors={errors} rate={rate:.1f}/s eta={(len(todo)-done)/max(rate,0.01)/60:.0f}m",
                flush=True,
            )
        time.sleep(delay)


if __name__ == "__main__":
    sys.exit(main())
