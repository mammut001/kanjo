"""Read effective subscription and quota fields and atomically edit overrides.json."""

import contextlib
import json
import os
import tempfile

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

from .config import (
    ConfigError, _antigravity_accounts, _subscriptions, _validate_agy_email,
    _validate_family_accounts, _validate_family_agents, _validate_family_device_name,
    _validate_family_since, antigravity_account_value, config_paths, family_value,
    load, quota_value, read_overrides, subscription_value,
)
from .quota import parse_weekly_reset
from .sources.base import AGENT_LABELS
from .subscriptions import known_plans_payload, subscriptions

AGENTS = tuple(AGENT_LABELS.keys())
SUBSCRIPTION_FIELDS = ("anchor_day", "plan", "monthly_price_usd")
QUOTA_FIELDS = ("weekly_reset",)
AGY_ACCOUNT_FIELDS = ("plan", "monthly_price_usd")


def _key(text):
    if text and text.startswith("antigravity_accounts."):
        rest = text[len("antigravity_accounts."):]
        email, sep, field = rest.rpartition(".")
        if sep == "." and field in AGY_ACCOUNT_FIELDS:
            return "antigravity_accounts", _validate_agy_email(email), field
    parts = (text or "").split(".")
    if len(parts) == 3:
        section, agent, field = parts[0], parts[1], parts[2]
        if section == "subscriptions" and agent in AGENTS and field in SUBSCRIPTION_FIELDS:
            return section, agent, field
        if section == "quota_windows" and agent in AGENTS and field in QUOTA_FIELDS:
            return section, agent, field
    elif len(parts) == 2:
        section, field = parts[0], parts[1]
        if section == "family" and field in ("since", "agents", "accounts", "device_name"):
            return section, None, field
    raise ConfigError(
        "key must be subscriptions.<agent>.<anchor_day|plan|monthly_price_usd>, "
        "quota_windows.<agent>.weekly_reset, "
        "antigravity_accounts.<email>.<plan|monthly_price_usd>, "
        "or family.<since|agents|accounts|device_name>"
    )


def _value(section, agent, key, text):
    if section == "antigravity_accounts":
        if key == "monthly_price_usd":
            try:
                value = float(text)
            except ValueError:
                raise ConfigError("monthly_price_usd must be a non-negative number")
            _antigravity_accounts({agent: {key: value}})
            return value
        validated = _antigravity_accounts({agent: {"plan": text}})
        return validated[agent]["plan"]
    if section == "family":
        if key == "since":
            return _validate_family_since(text)
        if key == "agents":
            return _validate_family_agents(text)
        if key == "accounts":
            return _validate_family_accounts(text)
        if key == "device_name":
            return _validate_family_device_name(text)
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


@contextlib.contextmanager
def _locked_overrides(path):
    """Serialize read-modify-write of overrides.json across processes via ``overrides.json.lock``."""
    lock_path = path + ".lock"
    try:
        os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
        handle = open(lock_path, "a+")
    except OSError as exc:
        raise ConfigError("cannot open %s: %s" % (lock_path, exc))
    with handle:
        if os.name == "nt":
            import msvcrt
            # msvcrt locks byte ranges from the current position; the file may be empty, which is fine.
            # LK_LOCK itself retries for about 10 s before raising.
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            except OSError as exc:
                raise ConfigError("cannot lock %s: %s" % (lock_path, exc))
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        elif fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        else:
            yield


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
        with _locked_overrides(path):
            data = read_overrides(path)
            raw = data.setdefault(section, {})
            if not isinstance(raw, dict):
                raise ConfigError("overrides %s must be an object" % section)
            if section == "family":
                if args.config_cmd == "set":
                    raw[key] = value
                else:
                    raw.pop(key, None)
                    if not raw:
                        data.pop(section, None)
            else:
                target_key = agent
                if section == "antigravity_accounts" and target_key not in raw:
                    for existing_k in raw:
                        if isinstance(existing_k, str) and existing_k.strip().lower() == agent:
                            target_key = existing_k
                            break
                spec = raw.setdefault(target_key, {})
                if not isinstance(spec, dict):
                    raise ConfigError("overrides %s.%s must be an object" % (section, target_key))
                if args.config_cmd == "set":
                    spec[key] = value
                else:
                    spec.pop(key, None)
                    if not spec:
                        raw.pop(target_key, None)
                    if section == "antigravity_accounts" and not raw:
                        data.pop(section, None)
            cfg = load(args.config, overrides=data)
            _write(path, data)

    if section == "subscriptions":
        value, origin = subscription_value(
            cfg, agent, key, subscriptions(cfg.subscriptions, antigravity_accounts=cfg.antigravity_accounts)
        )
        if key == "anchor_day" and value is None:
            print("%s = unset (rolling 30 days)" % args.key)
        else:
            print("%s = %s (%s)" % (args.key, json.dumps(value, ensure_ascii=False), origin))
    elif section == "antigravity_accounts":
        value, origin = antigravity_account_value(cfg, agent, key)
        if value is None:
            print("%s = unset (%s)" % (args.key, origin))
        else:
            print("%s = %s (%s)" % (args.key, json.dumps(value, ensure_ascii=False), origin))
    elif section == "quota_windows":
        value, origin = quota_value(cfg, agent, key)
        if value is None:
            print("%s = unset (%s)" % (args.key, origin))
        else:
            print("%s = %s (%s)" % (args.key, json.dumps(value, ensure_ascii=False), origin))
    elif section == "family":
        value, origin = family_value(cfg, key)
        if value is None:
            print("%s = unset (%s)" % (args.key, origin))
        else:
            print("%s = %s (%s)" % (args.key, json.dumps(value, ensure_ascii=False), origin))
    return 0
