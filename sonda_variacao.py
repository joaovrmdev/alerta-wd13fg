"""Sonda temporária: mesma oferta analisada várias vezes — o que muda entre as rodadas."""
import os, time
from datetime import datetime
import requests
import cacador as c

chave = os.environ["GEMINI_API_KEY"]
agora = datetime.now(c.BRT)
ofertas = []
for nome, func in c.FONTES.items():
    try:
        ofertas += func(c.CFG["fontes"].get(nome) or {})
    except Exception as e:  # noqa: BLE001
        print("falha", nome, e)
for o in ofertas:
    o.motivos = c.motivos(o) or ["teste"]
alvos = [("Cama Box", 5, 3), ("NBA", 4, 0)]
for termo, n_livre, n_seed in alvos:
    o = next((x for x in ofertas if termo.lower() in x.titulo.lower()), None)
    if not o:
        print("\n(não achei", termo, ")"); continue
    print(f"\n===== {c.brl(o.preco)} {o.desconto}% | {o.loja} | {o.titulo}\n{c.descreve(o, agora)}\n")
    for i in range(n_livre + n_seed):
        seed = 42 if i >= n_livre else None
        gc = {"thinkingConfig": {"includeThoughts": True}}
        if seed is not None:
            gc["seed"] = seed
        corpo = {"systemInstruction": {"parts": [{"text": c.INSTRUCOES}]},
                 "contents": [{"role": "user", "parts": [{"text": c.descreve(o, agora)}]}],
                 "tools": [{"google_search": {}}], "generationConfig": gc}
        r = requests.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
                          headers={"x-goog-api-key": chave}, json=corpo, timeout=120)
        if r.status_code != 200:
            print(f"  #{i+1} HTTP {r.status_code} {r.text[:150]}"); continue
        d = r.json(); cand = (d.get("candidates") or [{}])[0]
        partes = (cand.get("content") or {}).get("parts") or []
        pens = " ".join(p.get("text", "") for p in partes if p.get("thought"))
        a = c.extrai_json("".join(p.get("text", "") for p in partes if not p.get("thought"))) or {}
        q = (cand.get("groundingMetadata") or {}).get("webSearchQueries") or []
        fontes = [ch.get("web", {}).get("title") for ch in (cand.get("groundingMetadata") or {}).get("groundingChunks") or []][:4]
        print(f"  #{i+1}{' seed' if seed is not None else ''}: {a.get('veredito')} {a.get('nota')}/10 normal={c.brl(a.get('preco_normal'))} honrar={a.get('chance_honrar')}")
        print(f"      buscas={q} fontes={fontes}")
        print(f"      resumo: {str(a.get('resumo'))[:220]}")
        print(f"      pensou: {' '.join(pens.split())[:420]}")
