"""Sonda temporária: todos os produtos do alerta em simulação, com a correção do plano B."""
import glob, os, subprocess, sys
for cfg in ["config.json"] + sorted(glob.glob("config-*.json")):
    r = subprocess.run([sys.executable, "alerta.py", "simulacao"], env=dict(os.environ, CONFIG=cfg),
                       capture_output=True, text=True, timeout=240)
    linhas = [l for l in (r.stdout + r.stderr).splitlines()
              if l.startswith(("[ok]", "[falha]", "Melhor preço", "Traceback", "[estado]")) or "Error" in l or "*" in l[:40]]
    print(f"\n### {cfg}")
    print("\n".join(linhas[:14]))
