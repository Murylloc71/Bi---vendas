"""Carga inicial a partir de uma pasta de planilhas.

Uso (dentro de backend/):
    python -m scripts.carga_inicial ../dados_iniciais 2026-10-22

Os arquivos são reconhecidos pelo conteúdo; o depósito do estoque vem do nome do
arquivo (ex.: Unlock.xlsx -> "Unlock"). Ordem: vendas, estoque, compras.
"""
import sys
from pathlib import Path

from app import db
from app import importadores as imp


def main(pasta: str, data_ref: str | None):
    db.criar_tabelas()
    arquivos = sorted(p for p in Path(pasta).iterdir() if p.suffix.lower() in (".xlsx", ".xls", ".csv"))
    preparados = [imp.preparar(p.name, p.read_bytes()) for p in arquivos]
    ordem = {"vendas": 0, "estoque": 1, "compras": 2}
    for prep in sorted(preparados, key=lambda x: (ordem.get(x["tipo"], 9), x["arquivo"])):
        if not prep["tipo"]:
            print(f"IGNORADO (tipo não reconhecido): {prep['arquivo']}")
            continue
        r = imp.executar(prep["token"], prep["tipo"], None, {"data_referencia": data_ref}, confirmar=True)
        s = r["resumo"]
        print(f"{prep['arquivo']:<28} {prep['tipo']:<8} adicionados={s['adicionados']} atualizados={s['atualizados']} "
              f"duplicados={s['duplicados']} rejeitados={s['rejeitados']}")
    imp.revincular_estoque()
    snap = Path(pasta) / "omie_pedidos.json"
    if snap.exists():
        from app import omie
        r = omie.importar_snapshot(snap)
        print(f"omie_pedidos.json            pedidos={r['pedidos']} itens={r['itens']} (instantâneo; a sincronização substitui)")
    # Vendas: a partir de outubro/2026 vêm das planilhas semanais (o relatório mensal desses meses fica guardado, sem uso)
    from app import main as _main
    _main._cfg_set("vendas_semanais_desde", _main.SEMANAL_PADRAO)
    print(f"Vendas por semana a partir de {_main.SEMANAL_PADRAO} (relatório mensal desse período fica guardado e desligado)")
    # Estoque: vem da API do Omie (Omie 03 = Unlock, Omie 04 = Juatuba), não mais de planilha
    from app import estoque_omie
    if any(estoque_omie.credenciais(c["id"])[0] for c in estoque_omie.CONTAS):
        try:
            r = estoque_omie.sincronizar()
            for x in r["resultados"]:
                print(f"Estoque {x['empresa']} ({x['deposito']}): {x['codigos']} códigos, {x['unidades']:.0f} unidades")
            for e in r["erros"]:
                print(f"!! Estoque {e}")
        except Exception as e:  # noqa: BLE001
            print(f"!! Estoque pelo Omie falhou: {e}")
    else:
        print("Estoque: configure OMIE03_APP_KEY/SECRET e OMIE04_APP_KEY/SECRET (ou a tela Dados › Omie) para trazer o estoque do Omie.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
