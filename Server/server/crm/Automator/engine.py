# -*- coding: utf-8 -*-
import json
import time

from db.models import AutomationRule, AutomationLog
from server.crm.Automator.conditions import eval_conditions
from server.crm.Automator.actions import ACTIONS


def _now_ms():
    return int(time.time() * 1000)


def run_event(s, company_id: int, event_name: str, ctx: dict, actor_user_id: int = 0):
    """
    s: SQLAlchemy session (ВАЖНО: без коммита внутри)
    ctx: dict (client_id, pipeline_id, stage_id, prev_stage_id, channel, region_id, etc.)
    """
    event_name = (event_name or "").strip()
    if not event_name:
        return

    rules = (
        s.query(AutomationRule)
        .filter(AutomationRule.company_id == int(company_id))
        .filter(AutomationRule.event_name == event_name)
        .filter(AutomationRule.enabled == True)
        .order_by(AutomationRule.priority.asc(), AutomationRule.id.asc())
        .all()
    )

    for r in rules:
        ok = True
        err = ""

        try:
            cond = {}
            try:
                cond = json.loads(r.conditions_json or "{}")
            except Exception:
                cond = {}

            if not eval_conditions(cond, ctx):
                continue

            acts = []
            try:
                acts = json.loads(r.actions_json or "[]")
            except Exception:
                acts = []

            for a in acts:
                atype = (a.get("type") or "").strip()
                fn = ACTIONS.get(atype)
                if not fn:
                    continue
                fn(s, company_id, ctx, a, actor_user_id=actor_user_id)

            # log success
            s.add(AutomationLog(
                company_id=int(company_id),
                rule_id=int(r.id),
                event_name=event_name,
                ok=True,
                error="",
                context_json=json.dumps(ctx, ensure_ascii=False),
                created_ts_ms=_now_ms(),
            ))

            if bool(getattr(r, "stop_on_match", True)):
                break

        except Exception as e:
            ok = False
            err = str(e)

            s.add(AutomationLog(
                company_id=int(company_id),
                rule_id=int(r.id),
                event_name=event_name,
                ok=False,
                error=err,
                context_json=json.dumps(ctx, ensure_ascii=False),
                created_ts_ms=_now_ms(),
            ))

            # если одно правило сломалось — не валим весь запрос
            continue