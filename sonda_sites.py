"""Sonda temporária: slugs de cupons no Promobit e o formato dos dados de cupom."""
import json, re, os
os.environ["CONFIG"] = "config-azzaro-wanted.json"
import alerta as a
for loja in ("epoca-cosmeticos", "drogaria-sao-paulo", "drogarias-pacheco", "extrafarma", "pague-menos", "americanas",
             "webcontinental", "mercado-livre", "amazon", "sephora", "beleza-na-web", "drogasil", "droga-raia"):
    url = f"https://www.promobit.com.br/cupons/loja/{loja}/"
    try:
        t, u = a.baixa(url)
    except Exception as e:
        print(f"{loja}: falhou {str(e)[:60]}"); continue
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    d = json.loads(m.group(1)) if m else {}
    primeiro = []
    def anda(x, prof=0):
        if prof > 12: return
        if isinstance(x, dict):
            if any(k.lower().startswith("coupon") for k in x) and not primeiro:
                primeiro.append(x)
            for v in x.values(): anda(v, prof + 1)
        elif isinstance(x, list):
            for v in x[:80]: anda(v, prof + 1)
    anda(d)
    print(f"{loja}: final={u[-45:]} | 1º cupom: {json.dumps(primeiro[0], ensure_ascii=False)[:600] if primeiro else 'nenhum'}")
