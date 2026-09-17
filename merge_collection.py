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
    old_requests = {}
    for folder in old.get("items") or []:
        for r in folder.get("items") or []:
            old_requests[r.get("info", {}).get("name")] = r
    for folder in merged.get("items") or []:
        for req in folder.get("items") or []:
            old_req = old_requests.get(req.get("info", {}).get("name"))
            if old_req is not None:
                _merge_request(req, old_req, stats)
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
