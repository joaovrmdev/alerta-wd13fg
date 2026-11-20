"""Sonda temporária: onde dá para monitorar o Azzaro Wanted EDT 100ml e se há histórico de preço."""
import json, os, re
from urllib.parse import quote
os.environ["CONFIG"] = "config.json"
import alerta as a

def nd(texto):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', texto, re.S)
    return json.loads(m.group(1)) if m else None

def chaves(x, alvo, cam="", out=None, prof=0):
    out = [] if out is None else out
    if prof > 14: return out
    if isinstance(x, dict):
        for k, v in x.items():
            if re.search(alvo, k, re.I):
                out.append((cam + "/" + k, v))
            chaves(v, alvo, cam + "/" + k, out, prof + 1)
    elif isinstance(x, list):
        for i, v in enumerate(x[:40]):
            chaves(v, alvo, cam + f"[{i}]", out, prof + 1)
    return out

for site in ("buscape", "zoom"):
    print(f"\n######## {site} busca")
    try:
        t, u = a.baixa(f"https://www.{site}.com.br/busca/{quote('azzaro wanted eau de toilette 100ml')}")
    except Exception as e:
        print("  falhou", e); continue
    d = nd(t)
    hits = (((d or {}).get("props") or {}).get("initialReduxState") or {}).get("hits", {}).get("hits") or []
    urls = []
    for h in hits[:12]:
        if h.get("name"):
            print(f"  {h.get('price')} | {h.get('name')[:80]} | {h.get('url')}")
            if str(h.get("url", "")).startswith("/perfume"):
                urls.append(h["url"])
    for url in urls[:2]:
        full = f"https://www.{site}.com.br{url}"
        print(f"\n  ---- página {full}")
        try:
            t2, _ = a.baixa(full)
        except Exception as e:
            print("   falhou", e); continue
        d2 = nd(t2)
        for cam, v in chaves(d2, r"hist|lowest|menor|minPrice|average|media")[:25]:
            print("   ", cam[-110:], "=", json.dumps(v, ensure_ascii=False)[:260])
        txt = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", t2)).split())
        for k in ("Histórico de Preços", "últimos", "menor preço"):
            i = txt.find(k)
            if i >= 0:
                print(f"    [{k}] …{txt[max(0, i-120):i+260]}")

for nome, url in (("Época (VTEX)", "https://www.epocacosmeticos.com.br/api/catalog_system/pub/products/search?ft=azzaro%20wanted"),
                  ("Drogaria SP (VTEX)", "https://www.drogariasaopaulo.com.br/api/catalog_system/pub/products/search?ft=azzaro%20wanted"),
                  ("Pacheco (VTEX)", "https://www.drogariaspacheco.com.br/api/catalog_system/pub/products/search?ft=azzaro%20wanted"),
                  ("Extrafarma (VTEX)", "https://www.extrafarma.com.br/api/catalog_system/pub/products/search?ft=azzaro%20wanted"),
                  ("Beleza na Web", "https://www.belezanaweb.com.br/wanted-azzaro-eau-de-toilette-perfume-masculino/"),
                  ("Amazon busca", "https://www.amazon.com.br/s?k=azzaro+wanted+eau+de+toilette+100ml"),
                  ("Mercado Livre loja", "https://lista.mercadolivre.com.br/loja/azzaro/wanted-edt-100ml")):
    print(f"\n######## {nome}")
    try:
        t, u = a.baixa(url)
    except Exception as e:
        print("  falhou", str(e)[:120]); continue
    print("  ok", len(t), u[:90])
    if t.lstrip()[:1] == "[":
        for p in json.loads(t)[:8]:
            for it in p.get("items", [])[:3]:
                for s in it.get("sellers", [])[:1]:
                    o = s.get("commertialOffer", {})
                    pix = [x.get("Value") for x in o.get("Installments", []) if "pix" in str(x.get("PaymentSystemName", "")).lower()]
                    print(f"   {o.get('Price')} pix={pix[:1]} qtd={o.get('AvailableQuantity')} | {p.get('productName')[:70]} / {it.get('name')}")
    else:
        txt = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", t)).split())
        for m in list(re.finditer(r"(?i)wanted", txt))[:4]:
            print("   …", txt[max(0, m.start()-60):m.start()+160])
