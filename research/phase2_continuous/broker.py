"""JSON-only DeepSeek broker. It has no market data, account, or order access."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import urllib.request

from .engine import canonical, digest
from .runtime import CONTRACT, atomic, utc


def api_key():
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if directory:
        path = Path(directory)/"deepseek-key"
        if path.is_file(): return path.read_text().strip()
    return os.environ.get("DEEPSEEK_API_KEY")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("redirect_forbidden")


def billing(usage):
    hit = int(usage.get("prompt_cache_hit_tokens",0))
    miss = int(usage.get("prompt_cache_miss_tokens",max(0,int(usage.get("prompt_tokens",0))-hit)))
    output = int(usage.get("completion_tokens",0))
    return {"input_cache_hit_tokens":hit,"input_cache_miss_tokens":miss,"output_tokens":output,
            "total_tokens":hit+miss+output,
            "usd_upper_estimate":(hit*.006+miss*.30+output*1.20)/1e6,
            "tariff":"documented_peak_upper_estimate_20260927"}


def call_deepseek(payload,key):
    body = {"model":"deepseek-flash","thinking":{"type":"disabled"},"max_tokens":1800,
            "response_format":{"type":"json_object"},
            "messages":[
              {"role":"system","content":
               "Return only JSON with candidates: four objects each containing parent, complete genes, hypothesis. "
               "Use exactly the supplied family schema and enum values. Improve weaknesses in validation folds, drawdown, "
               "cost drag and concentration. Do not propose code or data changes. The outer and forward periods are unavailable."},
              {"role":"user","content":canonical(payload)}]}
    request = urllib.request.Request("https://api.deepseek.com/chat/completions",data=canonical(body).encode(),
             headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(request,timeout=45) as response:
        raw = response.read(250000)
    reply = json.loads(raw)
    return reply["choices"][0]["message"]["content"], billing(reply.get("usage",{})),reply.get("model")


def broker_once(root, transport=call_deepseek):
    root = Path(root)
    requests = sorted((root/"requests").glob("*.json"))
    responses = root/"responses";responses.mkdir(parents=True,exist_ok=True)
    inflight = root/"inflight";inflight.mkdir(parents=True,exist_ok=True)
    for request_path in requests:
        key_hash = request_path.stem
        result_path = responses/(key_hash+".json")
        if result_path.exists(): continue
        request = json.loads(request_path.read_text())
        payload = request["payload"]
        if request["hash"]!=key_hash or digest(payload)!=key_hash or payload.get("scope")!="development_inner_validation_only":
            raise ValueError("request_binding_or_scope")
        if (inflight/(key_hash+".json")).exists():
            atomic(result_path,{"hash":key_hash,"state":"FALLBACK","content":None,
                                "error":"uncertain_prior_call_no_retry","usage":{"api_call":1,"uncertain":True},"utc":utc()})
            return True
        cycle = payload["cycle_id"]
        usage = []
        for path in responses.glob("*.json"):
            try:
                row = json.loads(path.read_text())
                prior = json.loads((root/"requests"/(path.stem+".json")).read_text())["payload"]
                if prior["cycle_id"]==cycle:usage.append(row.get("usage") or {})
            except (OSError,ValueError,KeyError):
                continue
        calls = sum(x.get("api_call",0) for x in usage)
        tokens = sum(x.get("total_tokens",0) for x in usage)
        dollars = sum(x.get("usd_upper_estimate",0) for x in usage)
        reason = None
        # Reserve a conservative input/output ceiling before any network call.
        reserved_tokens = len(canonical(payload).encode()) + 1800
        reserved_usd = (len(canonical(payload).encode())*.30+1800*1.20)/1e6
        if (calls >= CONTRACT["api_calls_per_cycle_max"] or
            tokens+reserved_tokens > CONTRACT["api_tokens_per_cycle_max"] or
            dollars+reserved_usd > CONTRACT["api_usd_per_cycle_max"]):
            reason = "cycle_api_budget"
        secret = api_key()
        if not secret: reason = "missing_api_key"
        if reason:
            atomic(result_path,{"hash":key_hash,"state":"FALLBACK","content":None,"error":reason,
                                "usage":{"api_call":0,"total_tokens":0,"usd_upper_estimate":0},"utc":utc()})
            return True
        # Reservation is durable before network I/O. An uncertain result is never retried.
        atomic(inflight/(key_hash+".json"),{"hash":key_hash,"utc":utc(),"reserved_call":1,
                                             "reserved_tokens":reserved_tokens,"reserved_usd":reserved_usd})
        try:
            content,bill,model = transport(payload,secret)
            result = {"hash":key_hash,"state":"COMPLETE","content":content,"error":None,
                      "usage":{"api_call":1,**bill},"model":model,"utc":utc()}
        except Exception as exc:
            result = {"hash":key_hash,"state":"FALLBACK","content":None,
                      "error":{"type":type(exc).__name__,"http_status":getattr(exc,"code",None)},
                      "usage":{"api_call":1,"uncertain":True,"total_tokens":0,"usd_upper_estimate":0},"utc":utc()}
        atomic(result_path,result)
        return True
    return False


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--mailbox",type=Path,required=True)
    args=parser.parse_args()
    print(canonical({"processed":broker_once(args.mailbox),"utc":utc()}))


if __name__=="__main__": main()
