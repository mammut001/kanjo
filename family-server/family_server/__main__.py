"""CLI entrypoint for family_server: serve, member, device, prune."""

import argparse
import json
import logging
import os
import sys
import time

from . import db
from .server import start_servers, stop_servers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("family_server")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    default_db = os.environ.get("FAMILY_DB", "/data/family.db")

    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument(
        "--db",
        default=argparse.SUPPRESS,
        help=f"Path to SQLite database file (default: {default_db}, env: FAMILY_DB)",
    )

    parser = argparse.ArgumentParser(
        prog="family_server",
        description="Kanjo family usage server CLI",
    )
    parser.add_argument(
        "--db",
        default=default_db,
        help=f"Path to SQLite database file (default: {default_db}, env: FAMILY_DB)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # serve
    serve_parser = subparsers.add_parser("serve", help="Run API and Dashboard servers", parents=[parent_parser])
    serve_parser.add_argument(
        "--api-port",
        type=int,
        default=int(os.environ.get("FAMILY_API_PORT", "8788")),
        help="Port for report API listener (default: 8788, env: FAMILY_API_PORT)",
    )
    serve_parser.add_argument(
        "--dashboard-port",
        type=int,
        default=int(os.environ.get("FAMILY_DASHBOARD_PORT", "8787")),
        help="Port for Tailscale dashboard listener (default: 8787, env: FAMILY_DASHBOARD_PORT)",
    )
    serve_parser.add_argument(
        "--api-host",
        default=os.environ.get("FAMILY_API_HOST", "127.0.0.1"),
        help="Host for report API listener (default: 127.0.0.1, env: FAMILY_API_HOST)",
    )
    serve_parser.add_argument(
        "--dashboard-host",
        default=os.environ.get("FAMILY_DASHBOARD_HOST", "127.0.0.1"),
        help="Host for dashboard listener (default: 127.0.0.1, env: FAMILY_DASHBOARD_HOST)",
    )
    serve_parser.add_argument(
        "--firebase-project-id",
        default=os.environ.get("FIREBASE_PROJECT_ID"),
        help="Firebase Project ID (env: FIREBASE_PROJECT_ID)",
    )
    serve_parser.add_argument(
        "--admin-emails",
        default=os.environ.get("FAMILY_ADMIN_EMAILS"),
        help="Comma-separated list of authorized admin emails (env: FAMILY_ADMIN_EMAILS)",
    )
    serve_parser.add_argument(
        "--public-origin",
        default=os.environ.get("FAMILY_PUBLIC_ORIGIN"),
        help="Allowed public Origin for CSRF checks (env: FAMILY_PUBLIC_ORIGIN)",
    )

    # member
    member_parser = subparsers.add_parser("member", help="Manage family members and tokens", parents=[parent_parser])
    member_subs = member_parser.add_subparsers(dest="member_action", required=True)

    add_parser = member_subs.add_parser("add", help="Add a new member and generate access token", parents=[parent_parser])
    add_parser.add_argument("name", help="Unique member name")

    list_parser = member_subs.add_parser("list", help="List registered members", parents=[parent_parser])

    revoke_parser = member_subs.add_parser("revoke", help="Revoke a member's access token", parents=[parent_parser])
    revoke_parser.add_argument("name", help="Name of member to revoke")

    merge_parser = member_subs.add_parser("merge", help="Merge one member into another", parents=[parent_parser])
    merge_parser.add_argument("--from", dest="from_name", required=True, help="Source member name to merge from")
    merge_parser.add_argument("--into", dest="into_name", required=True, help="Target member name to merge into")

    tokens_parser = member_subs.add_parser("tokens", help="List tokens for a member", parents=[parent_parser])
    tokens_parser.add_argument("--member", required=True, help="Member name")

    # device
    device_parser = subparsers.add_parser("device", help="Manage member devices", parents=[parent_parser])
    device_subs = device_parser.add_subparsers(dest="device_action", required=True)

    dev_list_parser = device_subs.add_parser("list", help="List devices for a member", parents=[parent_parser])
    dev_list_parser.add_argument("--member", required=True, help="Member name")

    dev_remove_parser = device_subs.add_parser("remove", help="Remove a device's reports for a member", parents=[parent_parser])
    dev_remove_parser.add_argument("--member", required=True, help="Member name")
    dev_remove_parser.add_argument("--device", required=True, help="Device ID (16 hex chars, or 'legacy')")

    # prune
    prune_parser = subparsers.add_parser("prune", help="Prune old and duplicate reports", parents=[parent_parser])

    args = parser.parse_args(argv)
    db_path = getattr(args, "db", default_db)

    # Ensure DB is initialized
    db.init_db(db_path)

    if args.subcommand == "serve":
        from .validation import validate_serve_env
        errors, firebase_config = validate_serve_env(
            public_origin=args.public_origin,
            firebase_config_raw=os.environ.get("FIREBASE_WEB_CONFIG_JSON"),
            admin_emails=args.admin_emails,
        )
        if errors:
            print("Error: Server startup configuration is invalid:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)

        admin_emails = {e.strip().lower() for e in args.admin_emails.split(",") if e.strip()}
        project_id = args.firebase_project_id or os.environ.get("FIREBASE_PROJECT_ID") or firebase_config.get("projectId")

        api_srv, dash_srv, a_port, d_port = start_servers(
            db_path=db_path,
            api_host=args.api_host,
            api_port=args.api_port,
            dashboard_host=args.dashboard_host,
            dashboard_port=args.dashboard_port,
            firebase_config=firebase_config,
            project_id=project_id,
            admin_emails=admin_emails,
            public_origin=args.public_origin,
        )
        print(f"Kanjo family server started.")
        print(f"  API listener:       http://{args.api_host}:{a_port}")
        print(f"  Dashboard listener: http://{args.dashboard_host}:{d_port}")
        print(f"  Database:           {db_path}")
        print("Press Ctrl+C to stop.")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down servers...")
            stop_servers(api_srv, dash_srv)
            print("Stopped.")
        return 0

    elif args.subcommand == "member":
        if args.member_action == "add":
            with db.get_connection(db_path) as conn:
                try:
                    token, member_id = db.add_member(conn, args.name)
                    print(f"Successfully added member '{args.name}' (ID: {member_id}).")
                    print(f"Token: {token}")
                    print("\nIMPORTANT: Store this token now. It will NEVER be shown again.")
                    return 0
                except ValueError as err:
                    print(f"Error: {err}", file=sys.stderr)
                    return 1

        elif args.member_action == "list":
            with db.get_connection(db_path) as conn:
                members = db.list_members(conn)
                if not members:
                    print("No members found.")
                    return 0
                id_to_name = {m["id"]: m["name"] for m in members}
                print(f"{'ID':<4} {'Name':<20} {'Created At':<26} {'Status'}")
                print("-" * 65)
                for m in members:
                    if m.get("merged_into") is not None:
                        target = id_to_name.get(m["merged_into"], f"#{m['merged_into']}")
                        ts = (m["revoked_at"] or "")[:19]
                        status = f"Merged into {target} ({ts})"
                    elif m["revoked_at"]:
                        status = f"Revoked ({m['revoked_at'][:19]})"
                    else:
                        status = "Active"
                    print(f"{m['id']:<4} {m['name']:<20} {m['created_at'][:19]:<26} {status}")
                return 0

        elif args.member_action == "revoke":
            with db.get_connection(db_path) as conn:
                try:
                    revoked = db.revoke_member(conn, args.name)
                    if revoked:
                        print(f"Successfully revoked token for member '{args.name}'.")
                    else:
                        print(f"Member '{args.name}' was already revoked.")
                    return 0
                except ValueError as err:
                    print(f"Error: {err}", file=sys.stderr)
                    return 1

        elif args.member_action == "merge":
            with db.get_connection(db_path) as conn:
                try:
                    from_m = db.get_member_by_name(conn, args.from_name)
                    if not from_m:
                        raise ValueError(f"Member '{args.from_name.strip()}' not found.")
                    into_m = db.get_member_by_name(conn, args.into_name)
                    if not into_m:
                        raise ValueError(f"Member '{args.into_name.strip()}' not found.")
                    res = db.merge_members(conn, from_m["id"], into_m["id"])
                    print(
                        f"Successfully merged '{from_m['name']}' into '{into_m['name']}': "
                        f"{res['tokens_moved']} token(s) moved, {res['reports_moved']} report(s) moved."
                    )
                    return 0
                except ValueError as err:
                    print(f"Error: {err}", file=sys.stderr)
                    return 1

        elif args.member_action == "tokens":
            with db.get_connection(db_path) as conn:
                try:
                    tokens = db.list_member_tokens(conn, args.member)
                except ValueError as err:
                    print(f"Error: {err}", file=sys.stderr)
                    return 1
                if not tokens:
                    print(f"No tokens found for member '{args.member}'.")
                    return 0
                print(f"{'ID':<4} {'Prefix':<10} {'Created At':<26} {'Status'}")
                print("-" * 65)
                for t in tokens:
                    if t["revoked_at"]:
                        status = f"Revoked ({t['revoked_at'][:19]})"
                    else:
                        status = "Active"
                    print(f"{t['id']:<4} {t['token_prefix']:<10} {t['created_at'][:19]:<26} {status}")
                return 0

    elif args.subcommand == "device":
        if args.device_action == "list":
            with db.get_connection(db_path) as conn:
                try:
                    devices = db.list_member_devices(conn, args.member)
                except ValueError as err:
                    print(f"Error: {err}", file=sys.stderr)
                    return 1
                if not devices:
                    print(f"No devices found for member '{args.member}'.")
                    return 0
                print(f"{'Device ID':<18} {'Name':<24} {'OS':<10} {'Reports':<8} {'Last Report'}")
                print("-" * 82)
                for dev in devices:
                    dev_id = dev["device_id"] or "(legacy)"
                    dev_name = dev.get("device_name") or "-"
                    dev_os = "-"
                    try:
                        payload = json.loads(dev["payload_json"])
                        if isinstance(payload.get("device"), dict) and payload["device"].get("os"):
                            dev_os = payload["device"]["os"]
                    except Exception:
                        pass
                    last_rec = (dev.get("received_at") or "")[:19]
                    print(f"{dev_id:<18} {dev_name:<24} {dev_os:<10} {dev['report_count']:<8} {last_rec}")
                return 0

        elif args.device_action == "remove":
            target_id = "" if args.device in ("", "legacy", "(legacy)") else args.device
            with db.get_connection(db_path) as conn:
                try:
                    deleted = db.remove_member_device(conn, args.member, target_id)
                except ValueError as err:
                    print(f"Error: {err}", file=sys.stderr)
                    return 1
                if deleted == 0:
                    print(
                        f"No reports found for device '{args.device}' under member '{args.member}'.",
                        file=sys.stderr,
                    )
                    return 1
                print(
                    f"Removed {deleted} report(s) for device '{args.device}' of member '{args.member}'."
                )
                return 0

    elif args.subcommand == "prune":
        with db.get_connection(db_path) as conn:
            deleted = db.prune_reports(conn)
            print(f"Pruned {deleted} report(s).")
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
