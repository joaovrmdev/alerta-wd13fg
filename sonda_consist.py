"""Sonda temporária: contraprova na cama box (sem comentários) e num bug de verdade inventado."""
from datetime import datetime, timedelta
import cacador as c
agora = datetime.now(c.BRT)
ofertas = c.promobit(c.CFG["fontes"]["promobit"])
o = next((x for x in ofertas if "cama box" in x.titulo.lower()), None)
o.motivos = c.motivos(o) or ["70% de desconto"]
o.vendido_por = "Mercado Livre"
print("\n--- Cama box, SEM comentários: só a contraprova, 3x")
for i in range(3):
    a = c.gemini(o, {}, agora, c.SEGUNDA_CHECAGEM)
    print(f"  => #{i+1}: {a['veredito']} {a['nota']}/10 | {str(a.get('resumo'))[:170]}")

bug = c.Oferta("Promobit", "999", "[BUG] Apple iPhone 16 128GB Preto", "https://www.promobit.com.br/oferta/x-999/",
               499.0, 5999.0, 92, "Amazon", publicado=agora - timedelta(minutes=8),
               texto="Corre que bugou! iPhone 16 128GB por R$ 499 vendido e entregue pela Amazon.")
bug.motivos = ["palavra de bug", "92% de desconto"]
bug.vendido_por = "Amazon"
print("\n--- Bug de verdade (simulado): análise completa com contraprova, 2x")
for i in range(2):
    a = c.analisa(bug, {}, agora)
    print(f"  => #{i+1}: {a['veredito']} {a['nota']}/10 honrar={a.get('chance_honrar')} | {str(a.get('resumo'))[:170]}")
