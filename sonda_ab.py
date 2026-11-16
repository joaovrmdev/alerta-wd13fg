"""Sonda temporária: análise com e sem a referência do Buscapé (raciocínio padrão)."""
from datetime import datetime
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
tot = {"sem": [0, 0, 0], "com": [0, 0, 0]}
for o in cands[:4]:
    print("\n=====", o.fonte, c.brl(o.preco), f"{o.desconto}%", "|", o.loja, "|", o.titulo[:90])
    refs = c.referencia_buscape(o)
    print("   busca:", c.termos_de_busca(o.titulo))
    for r in refs:
        print(f"   ref: {r['nome'][:80]} | {c.brl(r['preco'])} | {r['lojas']} lojas")
    for rotulo, lista in (("sem", []), ("com", refs)):
        o.referencias = lista
        a = c.gemini(o, {}, agora)
        u = a["_uso"]
        tot[rotulo][0] += u["entrada"]; tot[rotulo][1] += u["saida"] + u["pensamento"]; tot[rotulo][2] += u["buscas"]
        print(f"   [{rotulo} ref] {a['veredito']} {a['nota']}/10 normal={c.brl(a.get('preco_normal'))} "
              f"| in {u['entrada']} out {u['saida']}+{u['pensamento']} buscas {u['buscas']} | {str(a.get('resumo'))[:150]}")
print("\nTOTAL (entrada, saída+raciocínio, buscas):", tot)
