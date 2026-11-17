"""Sonda temporária: a cama box com a versão nova (com e sem comentários), 3x cada."""
import json, re
from datetime import datetime
import cacador as c
agora = datetime.now(c.BRT)
ofertas = c.promobit(c.CFG["fontes"]["promobit"])
for termo, rodadas in (("Cama Box", 3), ("NBA", 1)):
    o = next((x for x in ofertas if termo.lower() in x.titulo.lower()), None)
    if not o:
        print("não achei", termo); continue
    o.motivos = c.motivos(o) or ["teste"]
    texto = c.baixa(o.url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', texto, re.S)
    so = (json.loads(m.group(1))["props"]["pageProps"].get("serverOffer") or {}) if m else {}
    print(f"\n##### {o.titulo} | chaves serverOffer: {sorted(so.keys())[:60]}")
    c.contexto_promobit(o)
    print("vendido por:", o.vendido_por, "| comentários:", o.comentarios)
    cmts = list(o.comentarios)
    for cenario, lista in (("COM comentários", cmts), ("SEM comentários (como no minuto em que o post sai)", [])):
        if termo == "NBA" and not lista:
            continue
        print(f"\n--- {cenario}")
        for i in range(rodadas):
            o.comentarios = list(lista)
            a = c.analisa(o, {}, agora)
            print(f"  => #{i+1}: {a['veredito']} {a['nota']}/10 normal={c.brl(a.get('preco_normal'))} | {str(a.get('resumo'))[:150]}")
