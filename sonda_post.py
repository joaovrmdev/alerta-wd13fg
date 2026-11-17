"""Sonda temporária: o que a página da oferta no Promobit tem além da API (descrição, comentários)."""
import json, re
import cacador as c

def anda(x, cam="", saida=None, prof=0):
    saida = [] if saida is None else saida
    if prof > 12:
        return saida
    if isinstance(x, dict):
        for k, v in x.items():
            if re.search(r"(?i)comment|descri|content|frete|shipping|text|body", k) and isinstance(v, (str, list)) and v:
                saida.append((cam + "/" + k, v))
            anda(v, cam + "/" + k, saida, prof + 1)
    elif isinstance(x, list):
        for i, v in enumerate(x[:15]):
            anda(v, cam + f"[{i}]", saida, prof + 1)
    return saida

for oid, slug in (("3207041", "cama-box-bau-casal-com-colchao-pillow-angel-molas-ensacadas-3207041"),
                  ("3223761", "camiseta-masculina-nba-super-soft-3223761")):
    print("\n#####", slug)
    for url in (f"https://api.promobit.com.br/offers/{oid}", f"https://api.promobit.com.br/offers/{oid}/comments",
                f"https://api.promobit.com.br/comments?offer_id={oid}"):
        try:
            d = c.baixa(url, json_=True)
            print("  API", url, "->", json.dumps(d, ensure_ascii=False)[:700])
        except Exception as e:  # noqa: BLE001
            print("  API", url, "falhou:", str(e)[:80])
    try:
        t = c.baixa(f"https://www.promobit.com.br/oferta/{slug}/")
    except Exception as e:  # noqa: BLE001
        print("  página falhou:", e); continue
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    print("  página", len(t), "| __NEXT_DATA__:", bool(m))
    if m:
        for cam, v in anda(json.loads(m.group(1)))[:25]:
            print("   ", cam[-90:], "=", json.dumps(v, ensure_ascii=False)[:300])
    txt = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", t)).split())
    for k in ("frete", "comentário", "Comentários"):
        i = txt.find(k)
        if i >= 0:
            print(f"   [{k}] …{txt[max(0, i-200):i+300]}")
