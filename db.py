"""Esquema do banco. Funciona com PostgreSQL (Replit: variável DATABASE_URL)
ou SQLite local (padrão: storage/bi.db)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer,
                        MetaData, String, Table, Text, UniqueConstraint, create_engine, event)

RAIZ = Path(__file__).resolve().parents[2]
STORAGE = Path(os.environ.get("STORAGE_DIR", RAIZ / "storage"))
STORAGE.mkdir(parents=True, exist_ok=True)
(STORAGE / "uploads").mkdir(exist_ok=True)


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{STORAGE / 'bi.db'}"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # O SQLAlchemy usaria o driver psycopg (v3) por padrão; o projeto instala psycopg2.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DB_URL = _url()
# pool_recycle: o Neon gratuito suspende o banco parado; conexões velhas são trocadas antes de falhar
engine = create_engine(DB_URL, future=True, pool_pre_ping=True, pool_recycle=300)

if DB_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

meta = MetaData()

importacoes = Table(
    "importacoes", meta,
    Column("id", Integer, primary_key=True),
    Column("tipo", String(20), nullable=False),           # vendas | estoque | compras
    Column("arquivo", String(255)),
    Column("armazenado_em", String(500)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("data_referencia", Date),
    Column("deposito", String(60)),
    Column("modo", String(20)),
    Column("status", String(20), default="ok"),          # ok | desfeita
    Column("resumo", Text),
    Column("mapeamento", Text),
)

produtos = Table(
    "produtos", meta,
    Column("id", Integer, primary_key=True),
    Column("sku", String(120), nullable=False, unique=True),
    Column("categoria", String(20), nullable=False),
    Column("modelo", String(120), nullable=False, index=True),
    Column("cabedal", String(40)),
    Column("cor", String(40)),
    Column("descricao", String(500)),
)

vendas_mensais = Table(
    "vendas_mensais", meta,
    Column("id", Integer, primary_key=True),
    Column("produto_id", Integer, ForeignKey("produtos.id"), nullable=False, index=True),
    Column("mes", Date, nullable=False, index=True),
    Column("unidades", Float, nullable=False, default=0),
    Column("unidades_ml", Float),
    Column("unidades_shopee", Float),
    Column("faturamento", Float),
    Column("curva", String(5)),
    Column("parcial", Boolean, default=False),
    Column("dias_cobertos", Integer),
    Column("importacao_id", Integer, ForeignKey("importacoes.id")),
    UniqueConstraint("produto_id", "mes", name="uq_venda_produto_mes"),
)

# Vendas lançadas por período (planilha SKU x quantidade, ex.: lista de produtos vendidos do dia).
# Somam-se às vendas mensais nos dias que o relatório mensal ainda não cobre.
vendas_lancamentos = Table(
    "vendas_lancamentos", meta,
    Column("id", Integer, primary_key=True),
    Column("importacao_id", Integer, ForeignKey("importacoes.id"), index=True),
    Column("codigo", String(160), nullable=False),
    Column("sku", String(120), index=True),
    Column("tamanho", String(20)),
    Column("canal", String(20), nullable=False),          # ml | shopee | nao_informado
    Column("data_inicio", Date, nullable=False, index=True),
    Column("data_fim", Date, nullable=False),
    Column("unidades", Float, nullable=False),
    Column("faturamento", Float),                         # unidades x ticket médio (None = estimar)
    Column("conta", String(60), nullable=False, default=""),  # conta/loja (opcional)
    Column("somar_sempre", Boolean, nullable=False, default=False),  # soma mesmo nos dias do relatório mensal
)

# Produtos marcados como em linha (True) ou fora de linha (False), por chave de modelo.
produtos_linha = Table(
    "produtos_linha", meta,
    Column("chave", String(160), primary_key=True),
    Column("em_linha", Boolean, nullable=False),
    Column("atualizado_em", DateTime, default=datetime.utcnow),
)

# SKUs que o usuário tirou do BI (somem de vendas, estoque, compras e pedidos).
skus_excluidos = Table(
    "skus_excluidos", meta,
    Column("sku", String(160), primary_key=True),
    Column("excluido_em", DateTime, default=datetime.utcnow),
)

# Itens comprados sem preço (relatório de notas: emitente, data, número e EAN do item).
# Servem para o calendário de compras; o SKU sai do EAN já visto nas compras e nos pedidos do Omie.
compras_itens = Table(
    "compras_itens", meta,
    Column("id", Integer, primary_key=True),
    Column("importacao_id", Integer, ForeignKey("importacoes.id"), index=True),
    Column("chave", String(300), nullable=False, unique=True),
    Column("fornecedor", String(200)),
    Column("numero_nota", String(60)),
    Column("data", Date, nullable=False, index=True),
    Column("valor_nota", Float),          # só para reconhecer a mesma nota nas planilhas de compras
    Column("ean", String(40), index=True),
)

# Unidades na "visão compra": kits convertidos em peças. Base para estoque/cobertura.
demanda_pecas = Table(
    "demanda_pecas", meta,
    Column("id", Integer, primary_key=True),
    Column("sku", String(120), nullable=False, index=True),
    Column("mes", Date, nullable=False),
    Column("unidades", Float, nullable=False, default=0),
    Column("parcial", Boolean, default=False),
    Column("dias_cobertos", Integer),
    Column("importacao_id", Integer, ForeignKey("importacoes.id")),
    UniqueConstraint("sku", "mes", name="uq_pecas_sku_mes"),
)

estoque_snapshots = Table(
    "estoque_snapshots", meta,
    Column("id", Integer, primary_key=True),
    Column("deposito", String(60), nullable=False),
    Column("data", Date, nullable=False),
    Column("importacao_id", Integer, ForeignKey("importacoes.id")),
    UniqueConstraint("deposito", "data", name="uq_snapshot_dep_data"),
)

estoque_itens = Table(
    "estoque_itens", meta,
    Column("id", Integer, primary_key=True),
    Column("snapshot_id", Integer, ForeignKey("estoque_snapshots.id", ondelete="CASCADE"),
           nullable=False, index=True),
    Column("codigo", String(160), nullable=False),
    Column("sku", String(120), index=True),     # SKU vinculado (None = sem vínculo)
    Column("tamanho", String(20)),
    Column("quantidade", Float, nullable=False),
    Column("vinculo", String(20)),              # padrao | exato | sufixo | manual | None
)

vinculos = Table(
    "vinculos", meta,
    Column("codigo", String(160), primary_key=True),
    Column("sku", String(120), nullable=False),
    Column("tamanho", String(20)),
    Column("criado_em", DateTime, default=datetime.utcnow),
)

compras = Table(
    "compras", meta,
    Column("id", Integer, primary_key=True),
    Column("importacao_id", Integer, ForeignKey("importacoes.id"), index=True),
    Column("linha_chave", String(300), nullable=False, unique=True),
    Column("nota_chave", String(200), nullable=False, index=True),
    Column("numero_nota", String(60)),
    Column("data", Date, nullable=False, index=True),
    Column("fornecedor", String(200)),
    Column("ean", String(40)),
    Column("sku_original", String(160)),
    Column("modelo", String(120), index=True),
    Column("sku", String(120)),
    Column("valor_unitario", Float, nullable=False),
    Column("preco_desconto", Float, nullable=False),
    Column("valor_nota", Float),
    Column("valor_produtos", Float),
    Column("quantidade", Float),
    Column("quantidade_origem", String(20)),    # arquivo | inferida | None
    Column("modalidade", String(10), nullable=False),  # PE | PROG
)

# Registro do estado anterior para permitir desfazer importações
alteracoes = Table(
    "alteracoes", meta,
    Column("id", Integer, primary_key=True),
    Column("importacao_id", Integer, ForeignKey("importacoes.id"), index=True),
    Column("tabela", String(40), nullable=False),
    Column("registro_id", Integer),
    Column("antes", Text),     # JSON da linha anterior; None = linha nova
)

mapeamentos = Table(
    "mapeamentos", meta,
    Column("id", Integer, primary_key=True),
    Column("tipo", String(20), nullable=False),
    Column("assinatura", String(64), nullable=False),
    Column("colunas", Text),
    Column("mapeamento", Text, nullable=False),
    Column("atualizado_em", DateTime, default=datetime.utcnow),
    UniqueConstraint("tipo", "assinatura", name="uq_mapeamento"),
)


configuracoes = Table(
    "configuracoes", meta,
    Column("chave", String(60), primary_key=True),
    Column("valor", Text),
    Column("atualizado_em", DateTime, default=datetime.utcnow),
)


omie_pedidos = Table(
    "omie_pedidos", meta,
    Column("id", BigInteger, primary_key=True, autoincrement=False),   # nCodPed
    Column("numero", String(30)),
    Column("numero_fornecedor", String(40)),
    Column("fornecedor_id", BigInteger),
    Column("fornecedor", String(200)),
    Column("fornecedor_cnpj", String(20)),
    Column("status", String(20), index=True),
    Column("etapa", String(4)),
    Column("data_inclusao", Date),
    Column("previsao", Date),
    Column("pares", Float),
    Column("pares_recebidos", Float),
    Column("valor_mercadoria", Float),
    Column("valor_total", Float),
    Column("frete", Float),
    Column("parcelas", Text),
    Column("condicao", String(10)),
    Column("observacao", Text),
    Column("atualizado_em", DateTime),
)

omie_itens = Table(
    "omie_itens", meta,
    Column("id", BigInteger, primary_key=True, autoincrement=False),   # nCodItem
    Column("pedido_id", BigInteger, ForeignKey("omie_pedidos.id", ondelete="CASCADE"), index=True),
    Column("codigo", String(160)),
    Column("sku", String(120), index=True),
    Column("modelo", String(40), index=True),
    Column("tamanho", String(10)),
    Column("ean", String(20)),
    Column("descricao", String(200)),
    Column("quantidade", Float),
    Column("quantidade_recebida", Float),
    Column("valor_unitario", Float),
    Column("valor_mercadoria", Float),
    Column("desconto", Float),
    Column("valor_total", Float),
)


# Colunas acrescentadas depois da criação da tabela: (tabela, coluna, DDL)
_COLUNAS_NOVAS = [
    ("vendas_lancamentos", "faturamento", "FLOAT"),
    ("vendas_lancamentos", "conta", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("vendas_lancamentos", "somar_sempre", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def criar_tabelas():
    meta.create_all(engine)
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as c:
        for tabela, coluna, ddl in _COLUNAS_NOVAS:
            if tabela in insp.get_table_names() and coluna not in {x["name"] for x in insp.get_columns(tabela)}:
                c.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {ddl}"))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
