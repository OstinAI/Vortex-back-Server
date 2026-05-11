# -*- coding: utf-8 -*-
def _get(ctx: dict, key: str):
    return ctx.get(key)

def _exists(ctx: dict, key: str):
    return key in ctx and ctx.get(key) is not None and ctx.get(key) != ""

def eval_conditions(node, ctx: dict) -> bool:
    """
    JSON:
      {"all":[ ... ]}
      {"any":[ ... ]}
      {"eq":["stage_id",10]}
      {"ne":["channel","whatsapp"]}
      {"in":["channel",["whatsapp","manual"]]}
      {"gt":["budget",100]}
      {"gte":["budget",100]}
      {"lt":["budget",100]}
      {"lte":["budget",100]}
      {"exists":["client_id"]}
      {"not_exists":["user_id"]}
    """
    if not node:
        return True

    if isinstance(node, dict):
        if "all" in node:
            arr = node.get("all") or []
            return all(eval_conditions(x, ctx) for x in arr)
        if "any" in node:
            arr = node.get("any") or []
            return any(eval_conditions(x, ctx) for x in arr)

        if "eq" in node:
            k, v = (node.get("eq") or [None, None])[:2]
            return _get(ctx, k) == v
        if "ne" in node:
            k, v = (node.get("ne") or [None, None])[:2]
            return _get(ctx, k) != v
        if "in" in node:
            k, arr = (node.get("in") or [None, []])[:2]
            val = _get(ctx, k)
            return val in (arr or [])
        if "gt" in node:
            k, v = (node.get("gt") or [None, None])[:2]
            try:
                return float(_get(ctx, k)) > float(v)
            except:
                return False
        if "gte" in node:
            k, v = (node.get("gte") or [None, None])[:2]
            try:
                return float(_get(ctx, k)) >= float(v)
            except:
                return False
        if "lt" in node:
            k, v = (node.get("lt") or [None, None])[:2]
            try:
                return float(_get(ctx, k)) < float(v)
            except:
                return False
        if "lte" in node:
            k, v = (node.get("lte") or [None, None])[:2]
            try:
                return float(_get(ctx, k)) <= float(v)
            except:
                return False
        if "exists" in node:
            k = (node.get("exists") or [None])[0]
            return _exists(ctx, k)
        if "not_exists" in node:
            k = (node.get("not_exists") or [None])[0]
            return not _exists(ctx, k)

        # неизвестное условие -> false (чтоб не делало лишнего)
        return False

    # если передали bool
    if isinstance(node, bool):
        return bool(node)

    return False