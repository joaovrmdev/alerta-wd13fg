"""Sonda temporária: roda o radar de verdade (simulação) e mede o ruído das réguas sem histórico."""
import sys, time
from concurrent.futures import ThreadPoolExecutor
import radar as r

t0 = time.time()
sys.argv = ["radar.py", "simulacao"]
r.main()
print(f"\nradar completo em {time.time()-t0:.0f}s")

lojas = [l for l in r.CFG["lojas"] if l.get("ativa", True)]
with ThreadPoolExecutor(5) as ex:
    res = list(ex.map(r.le_loja, lojas))
itens = [i for _, its, _, _ in res for i in its]
por_ean = {}
for it in itens:
    if it.ean:
        por_ean.setdefault(it.ean, set()).add(it.grupo)
print("EANs:", len(por_ean), "| em 2+ empresas:", sum(len(g) >= 2 for g in por_ean.values()),
      "| nas 3:", sum(len(g) >= 3 for g in por_ean.values()))
hoje = __import__("datetime").date.today().toordinal()
for b, cpct in ((30, 70), (40, 80), (50, 85)):
    r.CFG["abaixo_outras_lojas_pct"] = b; r.CFG["desconto_declarado_pct"] = cpct
    ach, _ = r.candidatos(itens, {}, hoje)
    nb = sum(any("outras lojas" in m for m in x.motivos) for x in ach)
    nc = sum(any('"de"' in m for m in x.motivos) for x in ach)
    print(f"régua outras lojas {b}% / 'de' {cpct}%: {len(ach)} candidatos ({nb} por outras lojas, {nc} por preço de)")
    for x in ach[:8]:
        print(f"    {x.item.loja}: {x.item.preco} | {x.motivos} | {x.item.nome[:60]} | {x.outras[:3]}")
import json
tam = len(json.dumps({i.chave: [[hoje - k, i.preco] for k in range(30)] for i in itens}, separators=(",", ":")))
print(f"histórico de 30 dias ocuparia ~{tam/1e6:.1f} MB (sem compressão)")
