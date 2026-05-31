import json
import urllib.request

body = json.dumps({
    "secretary_context_request": {
        "request_id": "enc-check-001",
        "user_request_full": "Di cosa abbiamo parlato di recente e a che punto siamo?",
        "intent": "memory_lookup",
    }
}).encode("utf-8")

req = urllib.request.Request(
    "http://127.0.0.1:8722/context",
    data=body,
    headers={"Content-Type": "application/json"},
)

with urllib.request.urlopen(req) as resp:
    print("Content-Type header:", resp.headers.get("Content-Type"))
    raw = resp.read()

data = json.loads(raw.decode("utf-8"))
summary = data["secretary_context_response"]["context_payload"]["summary"]

print("\nSUMMARY:\n", summary)
print("\nREPR (la prova del nove):\n", repr(summary))
