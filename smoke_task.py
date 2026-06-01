"""Smoke 3b-2b — /task logica reale.
Avvia prima il server:  uv run segretario http-server
Poi (stesso token):     uv run python smoke_task.py
Incolla tutto l'output.
"""
import os
import time
import httpx

BASE = "http://127.0.0.1:8722/task"
TOKEN = os.environ.get("IL_SEGRETARIO_HTTP_TOKEN", "smoke-token-123")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# (etichetta, domain, action_type, action_name, original_input, user_visible_goal)
SHOTS = [
    ("1 completed   (vault/read_only)",    "vault",            "read_only",       "search", "cerca le mie note sul progetto X",            "trovare note su X"),
    ("2 confirm     (gmail/external_eff)",  "gmail",            "external_effect", "send",   "invia una mail a Marco per spostare la call", "inviare email a Marco"),
    ("3 refused_dom (dangerous_action)",    "dangerous_action", "execute",         "shell",  "esegui uno script di pulizia",                "eseguire script"),
    ("4 unmapped    (pippo/pluto)",         "pippo",            "pluto",           "boh",    "fai qualcosa di indefinito",                  "qualcosa"),
    ("5 split       (calendar/write)",      "calendar",         "write",           "create", "crea un evento martedì con Anna",             "creare evento con Anna"),
]

# --- Auth check: senza token deve dare 401 ---
try:
    na = httpx.post(BASE, json={"secretary_task_request": {"request": {"request_id": "noauth"}}}, timeout=10)
    print(f"[auth] no-token -> HTTP {na.status_code}  (atteso 401)")
except Exception as e:
    print(f"[auth] errore: {e}")

for i, (label, dom, act, name, original, goal) in enumerate(SHOTS, 1):
    body = {
        "secretary_task_request": {
            "request": {"request_id": f"smoke-{i}"},
            "task": {"domain": dom, "action_type": act, "action_name": name},
            "user_request": {"original_input": original, "user_visible_goal": goal},
            "privacy": {"private_data_needed": True},  # forza il path di recall (Correzione 1)
        }
    }
    t0 = time.time()
    try:
        r = httpx.post(BASE, headers=HEADERS, json=body, timeout=180)
    except Exception as e:
        print(f"\n=== {label} ===\nERRORE rete: {e}")
        continue
    dt = time.time() - t0
    print(f"\n=== {label}   [HTTP {r.status_code}]   {dt:.1f}s ===")
    try:
        data = r.json()
    except Exception:
        print("(body non-JSON):", r.text[:400])
        continue
    res = data.get("secretary_task_result", data)
    status = res.get("status", {})
    print("  state              :", status.get("state"), "| reason:", status.get("reason"))
    print("  confirmation.required:", res.get("confirmation", {}).get("required"))
    print("  ownership.owner    :", res.get("ownership", {}).get("output_owner"))
    print("  privacy.sanitized  :", res.get("privacy", {}).get("output_sanitized_by_secretary"))
    print("  audit.stored       :", res.get("audit", {}).get("stored"))
    content = (res.get("final_response", {}) or {}).get("content") or ""
    print("  content            :", content[:500])

print("\n--- fine. Ora controlla l'audit:  Get-Content state\\audit\\events.jsonl -Tail 10 ---")
