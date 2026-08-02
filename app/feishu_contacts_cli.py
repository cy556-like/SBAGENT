"""Command line maintenance for the Feishu organization directory."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.auth.feishu_contacts import latest_sync_status, run_full_sync


def main() -> int:
    parser = argparse.ArgumentParser(description="SBAGENT 飞书通讯录同步")
    subparsers = parser.add_subparsers(dest="command", required=True)
    sync_parser = subparsers.add_parser("sync", help="执行全量通讯录同步")
    sync_parser.add_argument("--full", action="store_true", help="全量同步（当前唯一模式）")
    sync_parser.add_argument("--tenant-key", default="", help="飞书租户 tenant_key")
    subparsers.add_parser("status", help="查看最近一次同步结果")
    args = parser.parse_args()

    if args.command == "sync":
        result = asyncio.run(run_full_sync(tenant_key=args.tenant_key, source="cli"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(latest_sync_status() or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
