import copy


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
    return merged, stats


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
