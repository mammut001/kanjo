"""Pure aggregation and merging across multiple devices for a single family member."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

TOKEN_KEYS = ("input", "output", "cache_read", "cache_write", "total")


def _parse_iso_utc(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        clean = ts.strip()
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _as_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _as_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _merge_periods(periods: List[dict], default_period: str = "all") -> dict:
    """Merge a list of Period dicts sharing the same period key."""
    if not periods:
        return {
            "period": default_period,
            "first_day": None,
            "last_day": None,
            "tokens": {k: 0 for k in TOKEN_KEYS},
            "cost_usd": 0.0,
            "by_provider": [],
            "by_agent": [],
            "top_models": [],
        }

    period_key = periods[0].get("period") or default_period
    starts = [p.get("start") for p in periods if isinstance(p.get("start"), str) and p.get("start")]
    first_days = [p.get("first_day") for p in periods if isinstance(p.get("first_day"), str) and p.get("first_day")]
    last_days = [p.get("last_day") for p in periods if isinstance(p.get("last_day"), str) and p.get("last_day")]

    tokens = {k: 0 for k in TOKEN_KEYS}
    total_cost = 0.0
    prov_agg: Dict[str, dict] = {}
    agent_agg: Dict[str, dict] = {}
    model_agg: Dict[str, dict] = {}
    models_used_set = set()
    has_models_used = False

    for p in periods:
        p_tok = p.get("tokens")
        if isinstance(p_tok, dict):
            for k in TOKEN_KEYS:
                tokens[k] += _as_int(p_tok.get(k))
        total_cost += _as_float(p.get("cost_usd"))

        for prov in p.get("by_provider") or ():
            if not isinstance(prov, dict):
                continue
            pkey = prov.get("provider")
            if not pkey or not isinstance(pkey, str):
                continue
            pe = prov_agg.setdefault(
                pkey,
                {
                    "provider": pkey,
                    "label": prov.get("label") or pkey.capitalize(),
                    "tokens": {k: 0 for k in TOKEN_KEYS},
                    "cost_usd": 0.0,
                    "models": {},
                },
            )
            if prov.get("label") and not pe["label"]:
                pe["label"] = prov["label"]
            pt = prov.get("tokens")
            if isinstance(pt, dict):
                for k in TOKEN_KEYS:
                    pe["tokens"][k] += _as_int(pt.get(k))
            pe["cost_usd"] += _as_float(prov.get("cost_usd"))

            for pm in prov.get("models") or ():
                if not isinstance(pm, dict):
                    continue
                mname = pm.get("model")
                if not mname or not isinstance(mname, str):
                    continue
                pme = pe["models"].setdefault(mname, {"model": mname, "tokens_total": 0, "cost_usd": 0.0})
                pme["tokens_total"] += _as_int(pm.get("tokens_total"))
                pme["cost_usd"] += _as_float(pm.get("cost_usd"))

        for ag in p.get("by_agent") or ():
            if not isinstance(ag, dict):
                continue
            akey = ag.get("agent")
            if not akey or not isinstance(akey, str):
                continue
            ae = agent_agg.setdefault(
                akey,
                {
                    "agent": akey,
                    "label": ag.get("label") or akey,
                    "tokens_total": 0,
                    "cost_usd": 0.0,
                },
            )
            if ag.get("label") and not ae["label"]:
                ae["label"] = ag["label"]
            ae["tokens_total"] += _as_int(ag.get("tokens_total"))
            ae["cost_usd"] += _as_float(ag.get("cost_usd"))

        for tm in p.get("top_models") or ():
            if not isinstance(tm, dict):
                continue
            mname = tm.get("model")
            if not mname or not isinstance(mname, str):
                continue
            me = model_agg.setdefault(
                mname,
                {
                    "model": mname,
                    "provider": tm.get("provider") or "",
                    "tokens_total": 0,
                    "cost_usd": 0.0,
                },
            )
            if tm.get("provider") and not me["provider"]:
                me["provider"] = tm["provider"]
            me["tokens_total"] += _as_int(tm.get("tokens_total"))
            me["cost_usd"] += _as_float(tm.get("cost_usd"))

        if isinstance(p.get("models_used"), list):
            has_models_used = True
            for mname in p["models_used"]:
                if isinstance(mname, str):
                    models_used_set.add(mname)

    by_provider = []
    for pe in prov_agg.values():
        p_models = [
            {
                "model": m["model"],
                "tokens_total": m["tokens_total"],
                "cost_usd": round(m["cost_usd"], 2),
            }
            for m in pe["models"].values()
        ]
        p_models.sort(key=lambda x: (-x["tokens_total"], -x["cost_usd"], x["model"]))
        by_provider.append(
            {
                "provider": pe["provider"],
                "label": pe["label"],
                "tokens": pe["tokens"],
                "cost_usd": round(pe["cost_usd"], 2),
                "models": p_models[:5],
            }
        )
    by_provider.sort(key=lambda x: (-x["tokens"]["total"], -x["cost_usd"], x["provider"]))

    by_agent = [
        {
            "agent": ae["agent"],
            "label": ae["label"],
            "tokens_total": ae["tokens_total"],
            "cost_usd": round(ae["cost_usd"], 2),
        }
        for ae in agent_agg.values()
    ]
    by_agent.sort(key=lambda x: (-x["tokens_total"], -x["cost_usd"], x["agent"]))

    top_models = []
    for me in model_agg.values():
        item = {
            "model": me["model"],
            "tokens_total": me["tokens_total"],
            "cost_usd": round(me["cost_usd"], 2),
        }
        if me["provider"]:
            item["provider"] = me["provider"]
        top_models.append(item)
    top_models.sort(key=lambda x: (-x["tokens_total"], -x["cost_usd"], x["model"]))
    top_models = top_models[:8]

    merged: Dict[str, Any] = {"period": period_key}
    if starts:
        merged["start"] = min(starts)
    merged.update(
        {
            "first_day": min(first_days) if first_days else None,
            "last_day": max(last_days) if last_days else None,
            "tokens": tokens,
            "cost_usd": round(total_cost, 2),
            "by_provider": by_provider,
            "by_agent": by_agent,
            "top_models": top_models,
        }
    )
    if has_models_used:
        merged["models_used"] = sorted(models_used_set)
    return merged


def merge_member_reports(reports: List[dict]) -> Optional[dict]:
    """Merge the latest per-device reports for a single member into a payload-like dict.

    Legacy rule:
    - A legacy report (device_id == '') is included only while there is no
      device-tagged report strictly newer than it.
    - Once any device-tagged report is newer than the legacy report, the legacy
      report is excluded and ``_meta['legacy_excluded']`` is True.
    """
    if not reports:
        return None

    parsed = []
    epoch_min = datetime.min.replace(tzinfo=timezone.utc)
    for r in reports:
        if not isinstance(r, dict):
            continue
        payload = r.get("payload")
        if not isinstance(payload, dict):
            raw_json = r.get("payload_json")
            if isinstance(raw_json, str):
                try:
                    payload = json.loads(raw_json)
                except Exception:
                    payload = {}
            else:
                payload = {}

        dev_obj = payload.get("device") if isinstance(payload.get("device"), dict) else {}
        device_id = r.get("device_id")
        if device_id is None:
            device_id = dev_obj.get("id") or ""
        device_id = str(device_id)

        device_name = r.get("device_name")
        if not device_name:
            device_name = dev_obj.get("name")

        rec_str = r.get("received_at")
        gen_str = r.get("generated_at") or payload.get("generated_at")
        rec_dt = _parse_iso_utc(rec_str)
        gen_dt = _parse_iso_utc(gen_str)
        sort_dt = rec_dt or gen_dt or epoch_min

        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        parsed.append(
            {
                "device_id": device_id,
                "device_name": device_name,
                "dev_obj": dev_obj,
                "received_at": rec_str,
                "received_dt": rec_dt,
                "generated_at": gen_str,
                "sort_dt": sort_dt,
                "payload": payload,
                "summary": summary,
            }
        )

    if not parsed:
        return None

    tagged = [item for item in parsed if item["device_id"]]
    legacy = [item for item in parsed if not item["device_id"]]

    legacy_excluded = False
    if legacy and tagged:
        max_tagged_dt = max(item["sort_dt"] for item in tagged)
        max_legacy_dt = max(item["sort_dt"] for item in legacy)
        if max_tagged_dt > max_legacy_dt:
            active = list(tagged)
            legacy_excluded = True
        else:
            active = tagged + legacy
    else:
        active = tagged + legacy

    # Order active reports newest-first
    active.sort(key=lambda item: item["sort_dt"], reverse=True)
    newest = active[0]

    # Merge summary
    all_time_list = [
        item["summary"]["all_time"]
        for item in active
        if isinstance(item["summary"].get("all_time"), dict)
    ]
    merged_summary: Dict[str, Any] = {
        "all_time": _merge_periods(all_time_list, default_period="all"),
    }
    for list_key in ("months", "weeks", "days"):
        grouped: Dict[str, List[dict]] = {}
        for item in active:
            for p in item["summary"].get(list_key) or ():
                if isinstance(p, dict) and isinstance(p.get("period"), str) and p["period"]:
                    grouped.setdefault(p["period"], []).append(p)
        merged_summary[list_key] = [
            _merge_periods(grouped[pk], default_period=pk)
            for pk in sorted(grouped.keys())
        ]

    # Plans: union across active devices (newest wins on key collision)
    merged_plans: Dict[str, str] = {}
    for item in reversed(active):
        p_plans = item["payload"].get("plans")
        if isinstance(p_plans, dict):
            for k, v in p_plans.items():
                if isinstance(k, str) and isinstance(v, str):
                    merged_plans[k] = v

    # Quota windows: from the device with the most recent report that has them
    merged_qw: Dict[str, Any] = {}
    for item in active:
        qw = item["payload"].get("quota_windows")
        if isinstance(qw, dict) and qw:
            merged_qw = qw
            break

    member_label = None
    for item in active:
        lbl = item["payload"].get("member_label")
        if isinstance(lbl, str) and lbl.strip():
            member_label = lbl
            break

    scope = None
    for item in active:
        sc = item["payload"].get("scope")
        if isinstance(sc, dict):
            scope = sc
            break

    devices_meta = []
    for item in active:
        dev = item["dev_obj"]
        all_t = item["summary"].get("all_time")
        all_t = all_t if isinstance(all_t, dict) else {}
        all_tokens = _as_int((all_t.get("tokens") or {}).get("total"))
        all_cost = round(_as_float(all_t.get("cost_usd")), 2)
        is_legacy = not bool(item["device_id"])
        display_name = (
            item["device_name"]
            or dev.get("name")
            or ("旧版客户端" if is_legacy else item["device_id"][:8])
        )
        devices_meta.append(
            {
                "device_id": item["device_id"],
                "device_name": display_name,
                "os": dev.get("os") or "",
                "generated_by": item["payload"].get("generated_by") or "—",
                "timezone": item["payload"].get("timezone") or "—",
                "received_at": item["received_dt"],
                "all_time_tokens": all_tokens,
                "all_time_cost": all_cost,
                "is_legacy": is_legacy,
                "quota_windows": item["payload"].get("quota_windows") if isinstance(item["payload"].get("quota_windows"), dict) else {},
                "plans": item["payload"].get("plans") if isinstance(item["payload"].get("plans"), dict) else {},
            }
        )

    return {
        "schema_version": newest["payload"].get("schema_version", 1),
        "kind": newest["payload"].get("kind", "kanjo-family-report"),
        "member_label": member_label,
        "generated_at": newest["generated_at"],
        "timezone": newest["payload"].get("timezone"),
        "generated_by": newest["payload"].get("generated_by"),
        "cost_note": newest["payload"].get("cost_note"),
        "scope": scope,
        "plans": merged_plans,
        "quota_windows": merged_qw,
        "summary": merged_summary,
        "_meta": {
            "devices": devices_meta,
            "legacy_excluded": legacy_excluded,
            "latest_received_at": newest["received_dt"] or newest["sort_dt"],
        },
    }
