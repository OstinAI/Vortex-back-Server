# -*- coding: utf-8 -*-
import json
import time
import threading

from db.connection import get_session
from db.models import AutomationJob, AutomationRule, AutomationLog, Client
from server.crm.Automator.actions import ACTIONS


def _now_ms():
    return int(time.time() * 1000)


def _day_start_ms(now_ms: int) -> int:
    lt = time.localtime(now_ms / 1000.0)
    start = time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))
    return int(time.mktime(start) * 1000)


def _hm_now(now_ms: int) -> str:
    lt = time.localtime(now_ms / 1000.0)
    return f"{lt.tm_hour:02d}:{lt.tm_min:02d}"


def _already_ran_today(s, rule_id: int, event_name: str, today_start: int) -> bool:
    already = (
        s.query(AutomationLog)
        .filter(AutomationLog.rule_id == int(rule_id))
        .filter(AutomationLog.event_name == str(event_name))
        .filter(AutomationLog.ok == True)
        .filter(AutomationLog.created_ts_ms >= int(today_start))
        .first()
    )
    return bool(already)


def _pick_targets_from_conditions(s, r: AutomationRule, cond: dict):
    """
    Поведение как в daily:
      - если cond.client_id -> одна цель
      - иначе cond.clients фильтр {pipeline_id, stage_id}
      - если ничего нет -> targets пусто (тогда запускаем 1 раз без client_id)
    """
    targets = []

    one_client_id = cond.get("client_id")
    try:
        one_client_id = int(one_client_id) if one_client_id is not None else 0
    except:
        one_client_id = 0

    if one_client_id > 0:
        return [one_client_id]

    f = cond.get("clients") or {}
    pid = f.get("pipeline_id")
    sid = f.get("stage_id")

    try:
        pid = int(pid) if pid is not None else 0
    except:
        pid = 0
    try:
        sid = int(sid) if sid is not None else 0
    except:
        sid = 0

    # если фильтра нет — вернём []
    if pid <= 0 and sid <= 0:
        return []

    q = s.query(Client).filter(Client.company_id == int(r.company_id))
    if pid > 0:
        q = q.filter(Client.pipeline_id == pid)
    if sid > 0:
        q = q.filter(Client.stage_id == sid)

    targets = [int(x.id) for x in q.order_by(Client.id.asc()).all()]
    return targets


def _run_actions_for_targets(s, r: AutomationRule, event_name: str, cond: dict, acts: list, targets: list, extra_ctx: dict):
    """
    Запуск:
      - если targets пусто -> 1 запуск без client_id
      - иначе по каждому client_id
    """
    now = _now_ms()

    if not targets:
        ctx = dict(extra_ctx or {})
        for a in acts:
            atype = (a.get("type") or "").strip()
            fn = ACTIONS.get(atype)
            if fn:
                fn(s, int(r.company_id), ctx, a, actor_user_id=0)

        s.add(AutomationLog(
            company_id=int(r.company_id),
            rule_id=int(r.id),
            event_name=event_name,
            ok=True,
            error="",
            context_json=json.dumps({"targets": 0, **(extra_ctx or {})}, ensure_ascii=False),
            created_ts_ms=now,
        ))
        return

    done = 0
    for client_id in targets:
        ctx = dict(extra_ctx or {})
        ctx["client_id"] = int(client_id)

        for a in acts:
            atype = (a.get("type") or "").strip()
            fn = ACTIONS.get(atype)
            if fn:
                fn(s, int(r.company_id), ctx, a, actor_user_id=0)

        done += 1

    s.add(AutomationLog(
        company_id=int(r.company_id),
        rule_id=int(r.id),
        event_name=event_name,
        ok=True,
        error="",
        context_json=json.dumps({"targets": done, **(extra_ctx or {})}, ensure_ascii=False),
        created_ts_ms=now,
    ))


# ---------------------------
# DAILY (оставил твой как есть)
# ---------------------------
def _run_daily_schedule(s, now_ms: int):
    hm = _hm_now(now_ms)
    today_start = _day_start_ms(now_ms)

    rules = (
        s.query(AutomationRule)
        .filter(AutomationRule.enabled == True)
        .filter(AutomationRule.event_name == "schedule_daily")
        .order_by(AutomationRule.priority.asc(), AutomationRule.id.asc())
        .all()
    )

    for r in rules:
        try:
            try:
                cond = json.loads(r.conditions_json or "{}")
            except:
                cond = {}

            at = (cond.get("at") or cond.get("daily_at") or cond.get("time") or "").strip()
            if not at or at != hm:
                continue

            if _already_ran_today(s, int(r.id), "schedule_daily", int(today_start)):
                continue

            try:
                acts = json.loads(r.actions_json or "[]")
            except:
                acts = []

            targets = _pick_targets_from_conditions(s, r, cond)

            _run_actions_for_targets(
                s, r, "schedule_daily", cond, acts, targets,
                extra_ctx={"schedule_at": at}
            )

        except Exception as e:
            s.add(AutomationLog(
                company_id=int(getattr(r, "company_id", 0)),
                rule_id=int(getattr(r, "id", 0)),
                event_name="schedule_daily",
                ok=False,
                error=str(e),
                context_json=json.dumps({"at": hm}, ensure_ascii=False),
                created_ts_ms=_now_ms(),
            ))


# ---------------------------
# WEEKLY
# cond: {"at":"09:00","dow":[0,2,4], ...}
# 0=Mon ... 6=Sun (tm_wday)
# ---------------------------
def _run_weekly_schedule(s, now_ms: int):
    lt = time.localtime(now_ms / 1000.0)
    hm = _hm_now(now_ms)
    today_start = _day_start_ms(now_ms)

    rules = (
        s.query(AutomationRule)
        .filter(AutomationRule.enabled == True)
        .filter(AutomationRule.event_name == "schedule_weekly")
        .order_by(AutomationRule.priority.asc(), AutomationRule.id.asc())
        .all()
    )

    for r in rules:
        try:
            try:
                cond = json.loads(r.conditions_json or "{}")
            except:
                cond = {}

            at = (cond.get("at") or "").strip()
            if at != hm:
                continue

            # поддержка: dow как список или weekday как одно число (для совместимости)
            dow = cond.get("dow")
            if isinstance(dow, list):
                try:
                    dows = [int(x) for x in dow]
                except:
                    dows = []
            else:
                try:
                    dows = [int(cond.get("weekday"))] if cond.get("weekday") is not None else []
                except:
                    dows = []

            if not dows or int(lt.tm_wday) not in dows:
                continue

            if _already_ran_today(s, int(r.id), "schedule_weekly", int(today_start)):
                continue

            try:
                acts = json.loads(r.actions_json or "[]")
            except:
                acts = []

            targets = _pick_targets_from_conditions(s, r, cond)

            _run_actions_for_targets(
                s, r, "schedule_weekly", cond, acts, targets,
                extra_ctx={"schedule_at": at, "dow": int(lt.tm_wday)}
            )

        except Exception as e:
            s.add(AutomationLog(
                company_id=int(getattr(r, "company_id", 0)),
                rule_id=int(getattr(r, "id", 0)),
                event_name="schedule_weekly",
                ok=False,
                error=str(e),
                context_json=json.dumps({"at": hm, "dow": int(lt.tm_wday)}, ensure_ascii=False),
                created_ts_ms=_now_ms(),
            ))


# ---------------------------
# MONTHLY
# cond: {"at":"09:00","dom":[1,15,28], ...}
# ---------------------------
def _run_monthly_schedule(s, now_ms: int):
    lt = time.localtime(now_ms / 1000.0)
    hm = _hm_now(now_ms)
    today_start = _day_start_ms(now_ms)

    rules = (
        s.query(AutomationRule)
        .filter(AutomationRule.enabled == True)
        .filter(AutomationRule.event_name == "schedule_monthly")
        .order_by(AutomationRule.priority.asc(), AutomationRule.id.asc())
        .all()
    )

    for r in rules:
        try:
            try:
                cond = json.loads(r.conditions_json or "{}")
            except:
                cond = {}

            at = (cond.get("at") or "").strip()
            if at != hm:
                continue

            dom = cond.get("dom")
            if isinstance(dom, list):
                try:
                    doms = [int(x) for x in dom]
                except:
                    doms = []
            else:
                # совместимость со старым "day"
                try:
                    doms = [int(cond.get("day"))] if cond.get("day") is not None else []
                except:
                    doms = []

            if not doms or int(lt.tm_mday) not in doms:
                continue

            if _already_ran_today(s, int(r.id), "schedule_monthly", int(today_start)):
                continue

            try:
                acts = json.loads(r.actions_json or "[]")
            except:
                acts = []

            targets = _pick_targets_from_conditions(s, r, cond)

            _run_actions_for_targets(
                s, r, "schedule_monthly", cond, acts, targets,
                extra_ctx={"schedule_at": at, "dom": int(lt.tm_mday)}
            )

        except Exception as e:
            s.add(AutomationLog(
                company_id=int(getattr(r, "company_id", 0)),
                rule_id=int(getattr(r, "id", 0)),
                event_name="schedule_monthly",
                ok=False,
                error=str(e),
                context_json=json.dumps({"at": hm, "dom": int(lt.tm_mday)}, ensure_ascii=False),
                created_ts_ms=_now_ms(),
            ))


# ---------------------------
# YEARLY
# cond: {"at":"09:00","md":["03-08","12-31"], ...}
# ---------------------------
def _run_yearly_schedule(s, now_ms: int):
    lt = time.localtime(now_ms / 1000.0)
    hm = _hm_now(now_ms)
    today_start = _day_start_ms(now_ms)

    rules = (
        s.query(AutomationRule)
        .filter(AutomationRule.enabled == True)
        .filter(AutomationRule.event_name == "schedule_yearly")
        .order_by(AutomationRule.priority.asc(), AutomationRule.id.asc())
        .all()
    )

    mmdd_today = f"{int(lt.tm_mon):02d}-{int(lt.tm_mday):02d}"

    for r in rules:
        try:
            try:
                cond = json.loads(r.conditions_json or "{}")
            except:
                cond = {}

            at = (cond.get("at") or "").strip()
            if at != hm:
                continue

            md = cond.get("md")
            if isinstance(md, list):
                mds = [str(x).strip() for x in md if str(x).strip()]
            else:
                # совместимость: month/day
                try:
                    m = int(cond.get("month") or 0)
                    d = int(cond.get("day") or 0)
                    mds = [f"{m:02d}-{d:02d}"] if m > 0 and d > 0 else []
                except:
                    mds = []

            if not mds or mmdd_today not in mds:
                continue

            if _already_ran_today(s, int(r.id), "schedule_yearly", int(today_start)):
                continue

            try:
                acts = json.loads(r.actions_json or "[]")
            except:
                acts = []

            targets = _pick_targets_from_conditions(s, r, cond)

            _run_actions_for_targets(
                s, r, "schedule_yearly", cond, acts, targets,
                extra_ctx={"schedule_at": at, "md": mmdd_today}
            )

        except Exception as e:
            s.add(AutomationLog(
                company_id=int(getattr(r, "company_id", 0)),
                rule_id=int(getattr(r, "id", 0)),
                event_name="schedule_yearly",
                ok=False,
                error=str(e),
                context_json=json.dumps({"at": hm, "md": mmdd_today}, ensure_ascii=False),
                created_ts_ms=_now_ms(),
            ))


# ---------------------------
# DATETIME (one-shot)
# cond: {"run_at_ts_ms": 1760000000000, ...}
# запускается один раз и выключает rule.enabled = False
# ---------------------------
def _run_datetime_schedule(s, now_ms: int):
    rules = (
        s.query(AutomationRule)
        .filter(AutomationRule.enabled == True)
        .filter(AutomationRule.event_name == "schedule_datetime")
        .order_by(AutomationRule.priority.asc(), AutomationRule.id.asc())
        .all()
    )

    for r in rules:
        try:
            try:
                cond = json.loads(r.conditions_json or "{}")
            except:
                cond = {}

            try:
                run_at = int(cond.get("run_at_ts_ms") or 0)
            except:
                run_at = 0

            if run_at <= 0:
                continue
            if run_at > int(now_ms):
                continue

            # дедуп: если уже есть успешный лог для этого правила и event_name — больше не трогаем
            already = (
                s.query(AutomationLog)
                .filter(AutomationLog.rule_id == int(r.id))
                .filter(AutomationLog.event_name == "schedule_datetime")
                .filter(AutomationLog.ok == True)
                .first()
            )
            if already:
                # на всякий случай выключим
                r.enabled = False
                continue

            try:
                acts = json.loads(r.actions_json or "[]")
            except:
                acts = []

            targets = _pick_targets_from_conditions(s, r, cond)

            _run_actions_for_targets(
                s, r, "schedule_datetime", cond, acts, targets,
                extra_ctx={"run_at_ts_ms": run_at}
            )

            # выключаем правило после выполнения
            r.enabled = False
            r.updated_ts_ms = _now_ms()

        except Exception as e:
            s.add(AutomationLog(
                company_id=int(getattr(r, "company_id", 0)),
                rule_id=int(getattr(r, "id", 0)),
                event_name="schedule_datetime",
                ok=False,
                error=str(e),
                context_json=json.dumps({}, ensure_ascii=False),
                created_ts_ms=_now_ms(),
            ))


def _worker_loop():
    while True:
        time.sleep(2)

        s = get_session()
        try:
            now = _now_ms()

            # schedule tick (раз в минуту)
            last_tick = getattr(_worker_loop, "_last_schedule_min", -1)
            cur_min = int(now // 60000)
            if cur_min != last_tick:
                _worker_loop._last_schedule_min = cur_min

                _run_daily_schedule(s, now)
                _run_weekly_schedule(s, now)
                _run_monthly_schedule(s, now)
                _run_yearly_schedule(s, now)
                _run_datetime_schedule(s, now)

            jobs = (
                s.query(AutomationJob)
                .filter(AutomationJob.status == "pending")
                .filter(AutomationJob.run_at_ts_ms <= now)
                .order_by(AutomationJob.run_at_ts_ms.asc(), AutomationJob.id.asc())
                .limit(30)
                .all()
            )

            if jobs:
                for j in jobs:
                    try:
                        try:
                            ctx = json.loads(j.ctx_json or "{}")
                        except:
                            ctx = {}
                        try:
                            a = json.loads(j.action_json or "{}")
                        except:
                            a = {}

                        fn = ACTIONS.get(j.action_type)
                        if fn:
                            fn(s, int(j.company_id), ctx, a, actor_user_id=0)

                        j.status = "done"
                        j.error = ""
                        j.updated_ts_ms = now

                    except Exception as e:
                        j.status = "failed"
                        j.error = str(e)
                        j.updated_ts_ms = now

            s.commit()

        except:
            try:
                s.rollback()
            except:
                pass
        finally:
            s.close()


def start_automator_worker():
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()