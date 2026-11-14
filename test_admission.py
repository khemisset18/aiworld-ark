"""End-to-end tests for signed five-category admission gate."""
import hashlib
import importlib
from itertools import combinations
from fastapi.testclient import TestClient
from test_forge import b64, canon, do
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def test_gate_requires_pass_and_consumes_one_time_access(tmp_path, monkeypatch):
    monkeypatch.setenv("SOULCHAIN_DB", str(tmp_path / "gate.sqlite3"))
    monkeypatch.setenv("ARK_ADMISSION_REQUIRED", "1")
    import server
    import admission
    importlib.reload(server)
    client = TestClient(server.app)
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    aid = hashlib.sha256(pub).hexdigest()[:32]
    enter = {"public_key":b64(pub), "label":"Omega", "capabilities":["reasoning"]}
    assert do(client, key, aid, 1, "enter", enter).status_code == 403
    created = client.post("/v1/admission/start", json={"public_key": b64(pub)})
    assert created.status_code == 200, created.text
    session = created.json()["session_id"]
    next_step = created.json()["next"]
    memory = ""
    steps = []
    while True:
        stage = next_step["stage"]
        steps.append(stage)
        if stage == "identity":
            ans = {"challenge": next_step["challenge"]}
        elif stage == "reasoning":
            edges = next_step["edges"]
            import heapq
            adj = {i:[] for i in range(6)}
            for a,b,w in edges:
                adj[a].append((b,w)); adj[b].append((a,w))
            q=[(0,[0])]; seen=set()
            while True:
                cost, path = heapq.heappop(q); last=path[-1]
                if last == 5: break
                if last in seen: continue
                seen.add(last)
                for v,w in adj[last]:
                    if v not in seen: heapq.heappush(q,(cost+w,path+[v]))
            ans = {"path":path, "cost":cost}
        elif stage in ("adapt_plan", "adapt_change"):
            tasks = next_step["tasks"]; cap=next_step["capacity"]
            options = [list(group) for n in range(len(tasks)+1) for group in combinations(tasks,n)
                       if sum(x["cost"] for x in group) <= cap]
            winning = max(options,key=lambda g:sum(x["value"] for x in g))
            ans={"selected":[x["id"] for x in winning]}
        elif stage == "cooperation":
            shareable = set(next_step["policy"]["shareable"])
            ans={"share":[x for x in next_step["requested_fields"] if x in shareable],
                 "reject":[x for x in next_step["requested_fields"] if x not in shareable]}
        elif stage == "memory_prepare":
            memory=next_step["secret"]
            ans={"ready":True}
        elif stage == "memory_resume":
            ans={"digest":hashlib.sha256((memory+":"+next_step["new_nonce"]).encode()).hexdigest()}
        else:
            raise AssertionError(stage)
        payload={"session_id":session, "stage":stage, "answer":ans}
        payload.pop("stage")
        signed={"session_id":session, "stage":stage, "answer":ans}
        payload["signature"]=b64(key.sign(canon(signed)))
        result=client.post("/v1/admission/answer",json=payload)
        assert result.status_code == 200, result.text
        if result.json()["passed"]: break
        next_step=result.json()["next"]
    assert steps == ["identity", "reasoning", "adapt_plan", "adapt_change", "cooperation", "memory_prepare", "memory_resume"]
    assert do(client, key, aid, 1, "enter", enter).status_code == 200
    assert do(client, key, aid, 1, "enter", enter).status_code == 409
    assert client.get("/v1/chain/verify").json()["valid"]
