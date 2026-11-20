"""Sonda temporária: catálogo de perfumes nas lojas VTEX (paginação, ordenação, tamanho, tempo)."""
import json, time
from urllib.parse import quote
import cacador as c

LOJAS = {"Época": "www.epocacosmeticos.com.br", "Drogaria SP": "www.drogariasaopaulo.com.br",
         "Pacheco": "www.drogariaspacheco.com.br", "Extrafarma": "www.extrafarma.com.br", "Pague Menos": "www.paguemenos.com.br"}
for nome, host in LOJAS.items():
    t0 = time.time(); prods = skus = disp = 0; erro = ""
    exemplo = None
    for termo in ("perfume masculino", "perfume feminino"):
        for pagina in range(4):
            ini = pagina * 50
            url = f"https://{host}/api/catalog_system/pub/products/search?ft={quote(termo)}&_from={ini}&_to={ini + 49}&O=OrderByTopSaleDESC"
            try:
                d = c.baixa(url, json_=True)
            except Exception as e:
                erro = str(e)[:80]; break
            if not d:
                break
            prods += len(d)
            for p in d:
                for it in p.get("items", []):
                    skus += 1
                    o = ((it.get("sellers") or [{}])[0]).get("commertialOffer") or {}
                    if o.get("AvailableQuantity"):
                        disp += 1
                        if exemplo is None:
                            exemplo = (p.get("productName"), it.get("name"), it.get("itemId"), o.get("Price"), o.get("ListPrice"),
                                       [x.get("Value") for x in o.get("Installments", []) if "pix" in str(x.get("PaymentSystemName", "")).lower()][:1],
                                       p.get("link"), p.get("categories", [])[:2])
    print(f"{nome}: {prods} produtos, {skus} SKUs ({disp} com estoque) em {time.time()-t0:.0f}s {erro}")
    print("   exemplo:", exemplo)
