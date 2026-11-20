"""Sonda temporária: histórico de preço na página de oferta do Promobit (menor/maior preço)."""
import json, re
import cacador as c

def anda(x, alvo, cam="", out=None, prof=0):
    out = [] if out is None else out
    if prof > 14: return out
    if isinstance(x, dict):
        for k, v in x.items():
            if re.search(alvo, k, re.I) and not isinstance(v, (dict, list)) or (re.search(alvo, k, re.I) and isinstance(v, (dict, list)) and len(json.dumps(v)) < 1500):
                out.append((cam + "/" + k, v))
            anda(v, alvo, cam + "/" + k, out, prof + 1)
    elif isinstance(x, list):
        for i, v in enumerate(x[:30]):
            anda(v, alvo, cam + f"[{i}]", out, prof + 1)
    return out

for url in ("https://www.promobit.com.br/oferta/perfume-masculino-azzaro-wanted-edt-100ml-3211946/",
            "https://www.promobit.com.br/oferta/perfume-azzaro-wanted-edt-100ml-3206118/"):
    print("\n#####", url)
    t = c.baixa(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    d = json.loads(m.group(1))
    so = d["props"]["pageProps"].get("serverOffer") or {}
    print("serverOffer:", json.dumps({k: v for k, v in so.items() if not isinstance(v, (dict, list)) or len(json.dumps(v)) < 300}, ensure_ascii=False)[:1800])
    for cam, v in anda(d["props"]["pageProps"], r"hist|lowest|highest|menor|maior|minPrice|maxPrice|priceChart|product")[:30]:
        print("  ", cam[-100:], "=", json.dumps(v, ensure_ascii=False)[:300])
    txt = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", t)).split())
    i = txt.find("Histórico de preço")
    print("  texto:", txt[i:i+300] if i >= 0 else "(sem 'Histórico de preço' no HTML)")
print("\n##### API de busca?")
for u in ("https://api.promobit.com.br/offers?q=azzaro%20wanted", "https://api.promobit.com.br/offers?search=azzaro%20wanted",
          "https://api.promobit.com.br/search?q=azzaro%20wanted"):
    try:
        d = c.baixa(u, json_=True, headers={"Origin": "https://www.promobit.com.br"})
        ofs = d.get("offers") if isinstance(d, dict) else d
        print(u, "->", [o.get("offer_title", "")[:50] for o in (ofs or [])[:5]])
    except Exception as e:
        print(u, "falhou", str(e)[:80])
