"""Sonda temporária: pesquisa livre x pesquisa direcionada a Zoom/Buscapé (mesmo modelo e ofertas)."""
import os, time
from datetime import datetime
import requests
import cacador as c

DIRECIONADA = c.INSTRUCOES.replace(
    "1. Use a pesquisa do Google para descobrir o preço normal do produto no Brasil hoje (lojas grandes, Buscapé, Zoom) e, se for marketplace, a reputação do vendedor.",
    "1. Para o preço normal, pesquise primeiro nos comparadores de preço, que mostram o menor preço atual e o histórico: "
    "faça a busca com a marca e o modelo do produto e \"site:zoom.com.br OR site:buscape.com.br\". "
    "Só pesquise em outros sites se os comparadores não tiverem o produto. Se for marketplace, veja também a reputação do vendedor.")
assert DIRECIONADA != c.INSTRUCOES
chave = os.environ["GEMINI_API_KEY"]
agora = datetime.now(c.BRT)
ofertas = []
for nome, func in c.FONTES.items():
    try:
        ofertas += func(c.CFG["fontes"].get(nome) or {})
    except Exception as e:  # noqa: BLE001
        print("falha", nome, e)
cands, vistos = [], set()
for o in ofertas:
    o.motivos = c.motivos(o)
    if o.motivos and c.chave_titulo(o) not in vistos:
        vistos.add(c.chave_titulo(o)); cands.append(o)
cands.sort(key=lambda o: ("palavra de bug" not in o.motivos, -(o.desconto or 0)))
print(len(ofertas), "ofertas,", len(cands), "candidatos")
tot = {k: [0, 0, 0, 0] for k in ("livre", "direcionada")}
for o in cands[:6]:
    print(f"\n===== {c.brl(o.preco)} {o.desconto}% | {o.loja} | {o.titulo[:90]}")
    for rotulo, instr in (("livre", c.INSTRUCOES), ("direcionada", DIRECIONADA)):
        corpo = {"systemInstruction": {"parts": [{"text": instr}]},
                 "contents": [{"role": "user", "parts": [{"text": c.descreve(o, agora)}]}],
                 "tools": [{"google_search": {}}]}
        t0 = time.time()
        r = requests.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
                          headers={"x-goog-api-key": chave}, json=corpo, timeout=120)
        if r.status_code != 200:
            print(f"  [{rotulo}] HTTP {r.status_code} {r.text[:120]}"); continue
        d = r.json(); cand = (d.get("candidates") or [{}])[0]
        a = c.extrai_json("".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [])) or {}
        u = d.get("usageMetadata") or {}
        q = (cand.get("groundingMetadata") or {}).get("webSearchQueries") or []
        t = tot[rotulo]; t[0] += u.get("promptTokenCount", 0); t[1] += u.get("candidatesTokenCount", 0); t[2] += u.get("thoughtsTokenCount", 0); t[3] += len(q)
        print(f"  [{rotulo}] {time.time()-t0:.0f}s in={u.get('promptTokenCount')} out={u.get('candidatesTokenCount')} pens={u.get('thoughtsTokenCount', 0)} "
              f"→ {a.get('veredito')} {a.get('nota')}/10 normal={c.brl(a.get('preco_normal'))}")
        print(f"      buscas: {q[:3]}")
print("\nTOTAL [entrada, saída, raciocínio, buscas]:", tot)
for k, (i, s, p, b) in tot.items():
    print(f"  {k}: custo estimado US$ {(i * 0.75 + (s + p) * 3.75) / 1e6:.4f}")
