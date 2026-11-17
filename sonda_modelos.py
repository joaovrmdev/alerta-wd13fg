"""Sonda temporária: modelo atual x modelos mais baratos, nas mesmas ofertas (prompt de produção)."""
import json, os, time
from datetime import datetime
import requests
import cacador as c

chave = os.environ["GEMINI_API_KEY"]
r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 200},
                 headers={"x-goog-api-key": chave}, timeout=30)
nomes = sorted(m["name"].split("/")[-1] for m in r.json().get("models", [])
               if "generateContent" in m.get("supportedGenerationMethods", []))
print("modelos com 'flash':", [n for n in nomes if "flash" in n and "image" not in n and "live" not in n and "tts" not in n])
lites = [n for n in nomes if "lite" in n and "image" not in n and "preview" not in n]
lites = sorted(lites, key=lambda n: [-float(x) if x.replace('.', '').isdigit() else 0 for x in n.split("-")[1:2]])
modelos = ["gemini-3.8-flash"] + lites[:2]
print("comparando:", modelos)

agora = datetime.now(c.BRT)
ofertas = []
for nome, func in c.FONTES.items():
    try:
        ofertas += func(c.CFG["fontes"].get(nome) or {})
    except Exception as e:  # noqa: BLE001
        print("falha", nome, e)
cands = []
for o in ofertas:
    o.motivos = c.motivos(o)
    if o.motivos:
        cands.append(o)
cands.sort(key=lambda o: ("palavra de bug" not in o.motivos, -(o.desconto or 0)))
vistos, unicos = set(), []
for o in cands:
    if c.chave_titulo(o) not in vistos:
        vistos.add(c.chave_titulo(o)); unicos.append(o)
print(len(ofertas), "ofertas,", len(unicos), "candidatos")
for o in unicos[:6]:
    print(f"\n===== {o.fonte} {c.brl(o.preco)} {o.desconto}% | {o.loja} | {o.titulo[:90]} | {o.motivos}")
    for modelo in modelos:
        corpo = {"systemInstruction": {"parts": [{"text": c.INSTRUCOES}]},
                 "contents": [{"role": "user", "parts": [{"text": c.descreve(o, agora)}]}],
                 "tools": [{"google_search": {}}]}
        t0 = time.time()
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                          headers={"x-goog-api-key": chave}, json=corpo, timeout=120)
        if r.status_code != 200:
            print(f"  [{modelo}] HTTP {r.status_code}: {r.text[:160]}"); continue
        d = r.json(); cand = (d.get("candidates") or [{}])[0]
        txt = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [])
        a = c.extrai_json(txt) or {}
        u = d.get("usageMetadata") or {}
        b = len((cand.get("groundingMetadata") or {}).get("webSearchQueries") or [])
        print(f"  [{modelo}] {time.time()-t0:.0f}s in={u.get('promptTokenCount')} out={u.get('candidatesTokenCount')} "
              f"pens={u.get('thoughtsTokenCount', 0)} buscas={b} → {a.get('veredito')} {a.get('nota')}/10 "
              f"normal={c.brl(a.get('preco_normal'))} honrar={a.get('chance_honrar')}")
        print(f"      {str(a.get('resumo'))[:170]}")
