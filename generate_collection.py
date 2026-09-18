#!/usr/bin/env python3
import argparse
import json
import pathlib
import sys

from core import SCRIPT_DIR, backup_existing, default_schema_dir, resolve_api_version
from formats import FORMATS, BuildContext


def default_out_path(fmt):
    return pathlib.Path(FORMATS[fmt].default_out)


def main():
    parser = argparse.ArgumentParser(description="Generate OpenCollection collection from vk-api-schema")
    parser.add_argument("--schema-dir", default=None, type=pathlib.Path)
    parser.add_argument("--out", default=None, type=pathlib.Path)
    parser.add_argument("--format", choices=tuple(FORMATS), default="tree")
    parser.add_argument("--api-version", default="latest", help="API version, or 'latest' to fetch from dev portal")
    parser.add_argument("--name", default="VK API")
    parser.add_argument("--all", action="store_true", help="include nodoc/hidden methods (default: public only)")
    parser.add_argument("--descriptions", default=SCRIPT_DIR / "data/parameter_descriptions.json", help="RU descriptions cache from dev portal")
    parser.add_argument("--dump-json", type=pathlib.Path, help="also dump the built object as JSON for verification")
    parser.add_argument("--merge", action="store_true", help="update existing output instead of replacing (tree, bundled, postman-v3, yaak, insomnia-v5)")
    parser.add_argument("--prune", action="store_true", help="delete requests and folders absent from the new schema (tree, bundled, postman-v3, yaak, insomnia-v5)")
    args = parser.parse_args()
    spec = FORMATS[args.format]
    if args.schema_dir is None:
        args.schema_dir = default_schema_dir()
    if args.out is None:
        args.out = default_out_path(args.format)
    if (args.merge or args.prune) and not spec.supports_merge:
        names = [n for n, s in FORMATS.items() if s.supports_merge]
        parser.error(f"--merge/--prune are only supported for {', '.join(names[:-1])} and {names[-1]}")
    ctx = BuildContext(
        schema_dir=args.schema_dir,
        api_version=resolve_api_version(args.api_version),
        name=args.name,
        descriptions=args.descriptions,
        include_all=args.all,
    )
    payload, stats = spec.build(ctx)
    merge_stats = None
    if args.merge and spec.load_existing is not None:
        import merge_collection
        old = spec.load_existing(args.out)
        if old is not None:
            payload, merge_stats = merge_collection.merge(
                payload, old, prune=args.prune, keep_old_items=spec.keep_old_items
            )
    if args.dump_json and spec.model_based:
        args.dump_json.parent.mkdir(parents=True, exist_ok=True)
        args.dump_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    backup = None
    if (args.merge or args.prune) and spec.supports_merge:
        backup = backup_existing(args.out)
    file_count, note = spec.write(payload, args.out)
    if args.out.is_dir():
        total = sum(f.stat().st_size for f in args.out.rglob("*") if f.is_file())
    else:
        total = args.out.stat().st_size
    size = f"{total / 1024 / 1024:.1f} MB"
    pruned_files = []
    if args.prune and spec.prune_orphans is not None:
        pruned_files = spec.prune_orphans(args.out, payload)
    extra = ""
    if backup is not None:
        extra += f" backup={backup.name}"
    if merge_stats is not None:
        extra += " " + " ".join(f"{k}={v}" for k, v in merge_stats.items())
    if pruned_files:
        extra += f" pruned_files={len(pruned_files)}"
    stat_bits = " ".join(f"{k}={stats[k]}" for k in spec.stats_keys)
    print(
        f"format={args.format} {stat_bits} "
        f"files={file_count} collisions={stats['collisions']} encodings={','.join(stats['encodings'])} "
        f"ru_descriptions={stats['ru_descriptions']} out={args.out}{note} ({size}){extra}"
    )


if __name__ == "__main__":
    sys.exit(main())
