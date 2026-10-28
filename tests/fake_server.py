"""Minimal test app-server; it never reads any real account credentials."""
import json
import sys
import time

mode = sys.argv[1]
if mode == 'hang':
    time.sleep(10)
    sys.exit()
init = json.loads(sys.stdin.readline())
assert init['method'] == 'initialize' and init['id'] == 1
print(json.dumps({'method': 'notice', 'params': {}}), flush=True)
print(json.dumps({'id': 1, 'result': {}}), flush=True)
ready = json.loads(sys.stdin.readline())
assert ready['method'] == 'initialized' and 'id' not in ready
read = json.loads(sys.stdin.readline())
assert read['method'] == 'account/rateLimits/read' and read['id'] == 2
if mode == 'error':
    print(json.dumps({'id': 2, 'error': {'code': -32600, 'message': 'authentication required'}}), flush=True)
else:
    print(json.dumps({'id': 2, 'result': {'rateLimitsByLimitId': {
        'codex': {'primary': {'usedPercent': 25, 'windowDurationMins': 120, 'resetsAt': None}, 'secondary': None},
        'extra': {'primary': {'usedPercent': 58, 'windowDurationMins': None, 'resetsAt': None}}
    }}}), flush=True)
