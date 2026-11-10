from execution_integrity_core import ExecutionIntegrityCore
from verify_export import verify_export

core = ExecutionIntegrityCore()

payload = {"tool": "search", "q": "agent execution"}
core.record("tool_call", payload, {"ok": True}, ts=1700000000.0)
payload["q"] = "mutated later"
print("Verification after harmless input mutation:", core.verify())
core.record("tool_call", {"tool": "calc", "expr": "2+2"}, {"result": 4}, ts=1700000001.0)

print("Verification before tamper:", core.verify())

path = core.export(filename="execution_log.json", exported_at=1700000002.0)

core.chain[0]["output"] = {"ok": False}
print("Verification after tamper:", core.verify())

verify_export(path)
