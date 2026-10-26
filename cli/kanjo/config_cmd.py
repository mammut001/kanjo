"""Read effective subscription fields and atomically edit overrides.json."""

import json
import os
import tempfile

from .config import ConfigError, _subscriptions, config_paths, load, read_overrides, subscription_value
from .sources.base import AGENT_LABELS
from .subscriptions import known_plans_payload, subscriptions

AGENTS = tuple(AGENT_LABELS.keys())
FIELDS = ("anchor_day", "plan", "monthly_price_usd")


def _key(text):
    parts = (text or "").split(".")
    if len(parts) != 3 or parts[0] != "subscriptions" or parts[1] not in AGENTS or parts[2] not in FIELDS:
        raise ConfigError("key must be subscriptions.<agent>.<anchor_day|plan|monthly_price_usd>")
    return parts[1], parts[2]


def _value(agent, key, text):
    try:
        if key == "anchor_day":
            value = int(text)
        elif key == "monthly_price_usd":
            value = float(text)
        else:
            value = text.strip()
    except ValueError:
        raise ConfigError("%s must be %s" % (key, "an integer from 1 to 28" if key == "anchor_day" else "a non-negative number"))
    # Unknown plans can be priced by another configured field; validate together in load().
    if key != "plan":
        _subscriptions({agent: {key: value}})
    elif not value:
        raise ConfigError("plan must be a non-empty string")
    return value


def _write(path, data):
    tmp = None
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".overrides-", suffix=".tmp", dir=os.path.dirname(path) or ".")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except (OSError, ValueError) as exc:
        raise ConfigError("cannot write %s: %s" % (path, exc))
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


def cmd_config(args):
    primary, path = config_paths(args.config)
    if args.config_cmd == "path":
        if args.key is not None or args.value is not None:
            raise ConfigError("config path takes no key or value")
        if getattr(args, "json", False):
            raise ConfigError("config path does not accept --json")
        print(primary)
        print(path)
        return 0
    if args.config_cmd == "plans":
        if args.key is not None or args.value is not None:
            raise ConfigError("config plans takes no key or value")
        import sys
        payload = known_plans_payload()
        if getattr(args, "json", False):
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            return 0
        lines = []
        for agent, plans in payload.items():
            lines.append("%s:" % agent)
            for p in plans:
                price = "$%.2f" % p["monthly_price_usd"] if p["monthly_price_usd"] is not None else "unknown"
                lines.append("  %-16s %s (%s)" % (p["key"], p["label"], price))
        sys.stdout.write("\n".join(lines) + "\n")
        return 0
    if getattr(args, "json", False):
        raise ConfigError("config %s does not accept --json" % args.config_cmd)
    agent, key = _key(args.key)
    if args.config_cmd == "set":
        if args.value is None:
            raise ConfigError("config set requires a value")
        value = _value(agent, key, args.value)
    elif args.value is not None:
        raise ConfigError("config %s takes no value" % args.config_cmd)

    if args.config_cmd == "get":
        cfg = load(args.config)
    else:
        data = read_overrides(path)
        raw = data.setdefault("subscriptions", {})
        if not isinstance(raw, dict):
            raise ConfigError("overrides subscriptions must be an object")
        spec = raw.setdefault(agent, {})
        if not isinstance(spec, dict):
            raise ConfigError("overrides subscriptions.%s must be an object" % agent)
        if args.config_cmd == "set":
            spec[key] = value
        else:
            spec.pop(key, None)
            if not spec:
                raw.pop(agent)
        cfg = load(args.config, overrides=data)
        _write(path, data)
    value, origin = subscription_value(cfg, agent, key, subscriptions(cfg.subscriptions))
    if key == "anchor_day" and value is None:
        print("%s = unset (rolling 30 days)" % args.key)
    else:
        print("%s = %s (%s)" % (args.key, json.dumps(value, ensure_ascii=False), origin))
    return 0
