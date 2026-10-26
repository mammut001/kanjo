"""Read effective subscription and quota fields and atomically edit overrides.json."""

import json
import os
import tempfile

from .config import ConfigError, _subscriptions, config_paths, load, quota_value, read_overrides, subscription_value
from .quota import parse_weekly_reset
from .sources.base import AGENT_LABELS
from .subscriptions import subscriptions

AGENTS = tuple(AGENT_LABELS.keys())
SUBSCRIPTION_FIELDS = ("anchor_day", "plan", "monthly_price_usd")
QUOTA_FIELDS = ("weekly_reset",)


def _key(text):
    parts = (text or "").split(".")
    if len(parts) == 3:
        section, agent, field = parts[0], parts[1], parts[2]
        if section == "subscriptions" and agent in AGENTS and field in SUBSCRIPTION_FIELDS:
            return section, agent, field
        if section == "quota_windows" and agent in AGENTS and field in QUOTA_FIELDS:
            return section, agent, field
    raise ConfigError("key must be subscriptions.<agent>.<anchor_day|plan|monthly_price_usd> or quota_windows.<agent>.weekly_reset")


def _value(section, agent, key, text):
    if section == "quota_windows":
        if key == "weekly_reset":
            try:
                norm, _, _, _ = parse_weekly_reset(text, "weekly_reset")
                return norm
            except ValueError as exc:
                raise ConfigError(str(exc))
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
        print(primary)
        print(path)
        return 0
    section, agent, key = _key(args.key)
    if args.config_cmd == "set":
        if args.value is None:
            raise ConfigError("config set requires a value")
        value = _value(section, agent, key, args.value)
    elif args.value is not None:
        raise ConfigError("config %s takes no value" % args.config_cmd)

    if args.config_cmd == "get":
        cfg = load(args.config)
    else:
        data = read_overrides(path)
        raw = data.setdefault(section, {})
        if not isinstance(raw, dict):
            raise ConfigError("overrides %s must be an object" % section)
        spec = raw.setdefault(agent, {})
        if not isinstance(spec, dict):
            raise ConfigError("overrides %s.%s must be an object" % (section, agent))
        if args.config_cmd == "set":
            spec[key] = value
        else:
            spec.pop(key, None)
            if not spec:
                raw.pop(agent)
        cfg = load(args.config, overrides=data)
        _write(path, data)

    if section == "subscriptions":
        value, origin = subscription_value(cfg, agent, key, subscriptions(cfg.subscriptions))
        if key == "anchor_day" and value is None:
            print("%s = unset (rolling 30 days)" % args.key)
        else:
            print("%s = %s (%s)" % (args.key, json.dumps(value, ensure_ascii=False), origin))
    else:
        value, origin = quota_value(cfg, agent, key)
        if value is None:
            print("%s = unset (%s)" % (args.key, origin))
        else:
            print("%s = %s (%s)" % (args.key, json.dumps(value, ensure_ascii=False), origin))
    return 0
