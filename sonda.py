"""Sonda temporária (só no PR de testes): o que a busca do Inter Shop devolve para a WD13FG."""
import json

from curl_cffi import requests

H = {"Accept": "application/json", "Origin": "https://shopping.inter.co", "Referer": "https://shopping.inter.co/"}
API = "https://marketplace-api.web.bancointer.com.br/site/affiliate/inter"


def get(caminho):
    r = requests.get(f"{API}/{caminho}", headers=H, timeout=30, impersonate="chrome")
    return r.status_code, r.text


for termo in ("wd13fg", "lava e seca samsung wd13fg", "lava e seca samsung 13kg"):
    st, txt = get(f"v1/ecommerce/search/products?limit=100&offset=0&searchText={termo}&lang=pt-BR")
    try:
        prods = json.loads(txt).get("products", [])
    except ValueError:
        print("[sonda]", termo, st, txt[:200])
        continue
    print(f"[sonda] '{termo}': {st}, {len(prods)} produtos; chaves: {sorted(prods[0].keys()) if prods else []}")
    for p in prods:
        nome = p.get("name", "")
        if "13" in nome and ("samsung" in nome.lower() or "wd" in nome.lower()):
            skus = [(s.get("id"), s.get("fullName") or s.get("name"), s.get("priceValue"), s.get("available"))
                    for s in p.get("skus", [])][:6]
            print(f"[sonda]   {p.get('id')} | {nome[:80]} | {p.get('priceValue')} | skus={skus}")
            if p.get("skus"):
                print(f"[sonda]   chaves sku: {sorted(p['skus'][0].keys())}")

for caminho in ("v1/ecommerce/products/11956898", "v1/ecommerce/products/11956898/skus",
                "v1/ecommerce/products/11956898?skuId=14851930", "v1/ecommerce/product/11956898",
                "v1/ecommerce/search/products?productIds=11956898&lang=pt-BR",
                "v1/ecommerce/search/products?ids=11956898&lang=pt-BR"):
    st, txt = get(caminho)
    print(f"[sonda] {caminho} -> {st} {txt[:300]!r}")
