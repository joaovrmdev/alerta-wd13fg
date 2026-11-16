"""Sonda temporária: mede tokens e buscas de cada análise do Gemini e compara níveis de raciocínio."""
import json, os, sys, time
from datetime import datetime
import requests
import cacador as c

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
print(len(ofertas), "ofertas,", len(cands), "candidatos")
modelo = c.CFG["gemini"]["modelos"][0]
chave = os.environ["GEMINI_API_KEY"]
for o in cands[:2]:
    print("\n=====", o.fonte, c.brl(o.preco), o.desconto, "% |", o.titulo[:90], "|", o.motivos)
    for nivel in (None, "low", "minimal"):
        corpo = {"systemInstruction": {"parts": [{"text": c.INSTRUCOES}]},
                 "contents": [{"role": "user", "parts": [{"text": c.descreve(o, agora)}]}],
                 "tools": [{"google_search": {}}]}
        if nivel:
            corpo["generationConfig"] = {"thinkingConfig": {"thinkingLevel": nivel}}
        t0 = time.time()
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                          headers={"x-goog-api-key": chave}, json=corpo, timeout=120)
        dt = time.time() - t0
        if r.status_code != 200:
            print(f"  [{nivel or 'padrão'}] HTTP {r.status_code}: {r.text[:300]}")
            continue
        d = r.json()
        cand = (d.get("candidates") or [{}])[0]
        texto = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or [])
        dados = c.extrai_json(texto) or {}
        buscas = (cand.get("groundingMetadata") or {}).get("webSearchQueries") or []
        print(f"  [{nivel or 'padrão'}] {dt:.0f}s uso={json.dumps(d.get('usageMetadata'))} buscas={len(buscas)} {buscas[:4]}")
        print(f"      → {dados.get('veredito')} {dados.get('nota')}/10 normal={dados.get('preco_normal')} honrar={dados.get('chance_honrar')} | {str(dados.get('resumo'))[:160]}")
