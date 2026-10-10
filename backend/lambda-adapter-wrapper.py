#!/usr/bin/env python3
import json
import os
import sys
import urllib.request

# Only run AWS Lambda Web Adapter if explicitly enabled or if an HTTP port is configured
if os.environ.get("AWS_LWA_ENABLE") == "false" or not os.environ.get("AWS_LWA_PORT"):
    api = os.environ.get("AWS_LAMBDA_RUNTIME_API")
    if api:
        req = urllib.request.Request(
            f"http://{api}/2020-01-01/extension/register",
            data=json.dumps({"events": ["INVOKE", "SHUTDOWN"]}).encode("utf-8"),
            headers={
                "Lambda-Extension-Name": "lambda-adapter",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                ext_id = resp.headers.get("Lambda-Extension-Identifier")
            if ext_id:
                next_req = urllib.request.Request(
                    f"http://{api}/2020-01-01/extension/event/next",
                    headers={"Lambda-Extension-Identifier": ext_id},
                    method="GET",
                )
                while True:
                    with urllib.request.urlopen(next_req) as next_resp:
                        evt = json.loads(next_resp.read().decode("utf-8"))
                        if evt.get("eventType") == "SHUTDOWN":
                            break
        except Exception:
            pass
    sys.exit(0)

os.execv("/opt/lambda-adapter-bin", [sys.argv[0]] + sys.argv[1:])
