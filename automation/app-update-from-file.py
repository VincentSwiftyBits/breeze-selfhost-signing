#!/usr/bin/python3
import json
import os
import sys

from truenas_api_client import Client


def main() -> int:
    if os.geteuid() != 0 or len(sys.argv) != 3:
        print("usage: app-update-from-file.py <app> <payload-file>", file=sys.stderr)
        return 64

    app, payload_path = sys.argv[1:]
    if app not in {"breeze-rmm-dev", "breeze-rmm-uat", "breeze-rmm"}:
        print("refusing unapproved TrueNAS app", file=sys.stderr)
        return 64

    with open(payload_path, "r", encoding="utf-8") as payload_file:
        payload = json.load(payload_file)

    with Client() as client:
        job = client.call("app.update", app, payload, job="RETURN")
        print(job.job_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
