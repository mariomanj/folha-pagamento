"""Persistência em SQLite (arquivo folha.db na pasta do projeto)."""
import sqlite3
from dataclasses import fields
from decimal import Decimal as D
from pathlib import Path

from .config import pasta_dados
from .calculo import VARIAVEIS, ZERO, Funcionario, Holerite, Lancamento, arred

def caminho_padrao() -> Path:
    return pasta_dados() / "folha.db"


# Tipos de folha gravados em folha_itens
FOLHAS = ("mensal", "ferias", "13-1", "13-2", "rescisao")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS funcionarios (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    nome             TEXT NOT NULL,
    cpf              TEXT UNIQUE,
    cargo            TEXT,
    admissao         TEXT,
    salario          TEXT NOT NULL,
    dependentes      INTEGER NOT NULL DEFAULT 0,
    usa_vt           INTEGER NOT NULL DEFAULT 0,
    valor_vt         TEXT NOT NULL DEFAULT '0',
    pensao           TEXT NOT NULL DEFAULT '0',
    insalubridade    INTEGER NOT NULL DEFAULT 0,
    periculosidade   INTEGER NOT NULL DEFAULT 0,
    filhos_sf        INTEGER NOT NULL DEFAULT 0,
    adiantamento_pct TEXT NOT NULL DEFAULT '0',
    desconto_vr      TEXT NOT NULL DEFAULT '0',
    matricula_esocial TEXT NOT NULL DEFAULT '',
    categoria        INTEGER NOT NULL DEFAULT 101,
    grau_exposicao   INTEGER NOT NULL DEFAULT 1,
    cpf_pensao       TEXT NOT NULL DEFAULT '',
    ativo            INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS lancamentos (
    funcionario_id   INTEGER NOT NULL REFERENCES funcionarios(id),
    competencia      TEXT NOT NULL,          -- AAAA-MM
    horas_extras_50  TEXT NOT NULL DEFAULT '0',
    horas_extras_100 TEXT NOT NULL DEFAULT '0',
    faltas_dias      TEXT NOT NULL DEFAULT '0',
    outros_proventos TEXT NOT NULL DEFAULT '0',
    outros_descontos TEXT NOT NULL DEFAULT '0',
    horas_noturnas   TEXT NOT NULL DEFAULT '0',
    comissoes        TEXT NOT NULL DEFAULT '0',
    dias_ferias      TEXT NOT NULL DEFAULT '0',
    feriados         TEXT NOT NULL DEFAULT '0',
    desconto_vt      TEXT NOT NULL DEFAULT '0',
    plano_saude      TEXT NOT NULL DEFAULT '0',
    plano_odonto     TEXT NOT NULL DEFAULT '0',
    vale_alimentacao TEXT NOT NULL DEFAULT '0',
    seguro_vida      TEXT NOT NULL DEFAULT '0',
    emprestimo_consignado TEXT NOT NULL DEFAULT '0',
    contribuicao_sindical TEXT NOT NULL DEFAULT '0',
    convenio_farmacia TEXT NOT NULL DEFAULT '0',
    PRIMARY KEY (funcionario_id, competencia)
);
CREATE TABLE IF NOT EXISTS folha_itens (
    funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id),
    competencia    TEXT NOT NULL,
    tipo           TEXT NOT NULL CHECK (tipo IN ('P', 'D', 'B')),  -- provento, desconto, base/informativo
    descricao      TEXT NOT NULL,
    valor          TEXT NOT NULL,
    folha          TEXT NOT NULL DEFAULT 'mensal'
);
"""
# Valores monetários são gravados como TEXT para não perder precisão do Decimal.

# Colunas criadas depois da primeira versão: adicionadas em bancos antigos
MIGRACOES = [
    ("funcionarios", "insalubridade", "INTEGER NOT NULL DEFAULT 0"),
    ("funcionarios", "periculosidade", "INTEGER NOT NULL DEFAULT 0"),
    ("funcionarios", "filhos_sf", "INTEGER NOT NULL DEFAULT 0"),
    ("funcionarios", "adiantamento_pct", "TEXT NOT NULL DEFAULT '0'"),
    ("funcionarios", "desconto_vr", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "horas_noturnas", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "comissoes", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "dias_ferias", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "feriados", "TEXT NOT NULL DEFAULT '0'"),
    ("folha_itens", "folha", "TEXT NOT NULL DEFAULT 'mensal'"),
    ("funcionarios", "matricula_esocial", "TEXT NOT NULL DEFAULT ''"),
    ("funcionarios", "categoria", "INTEGER NOT NULL DEFAULT 101"),
    ("funcionarios", "grau_exposicao", "INTEGER NOT NULL DEFAULT 1"),
    ("funcionarios", "cpf_pensao", "TEXT NOT NULL DEFAULT ''"),
    ("lancamentos", "desconto_vt", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "plano_saude", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "plano_odonto", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "vale_alimentacao", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "seguro_vida", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "emprestimo_consignado", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "contribuicao_sindical", "TEXT NOT NULL DEFAULT '0'"),
    ("lancamentos", "convenio_farmacia", "TEXT NOT NULL DEFAULT '0'"),
    ("funcionarios", "usa_vt", "INTEGER NOT NULL DEFAULT 0"),
]
# Executado uma vez, logo após criar a coluna em banco antigo
AJUSTES_MIGRACAO = {
    ("funcionarios", "usa_vt"): "UPDATE funcionarios SET usa_vt = 1 WHERE CAST(valor_vt AS REAL) > 0",
}

CAMPOS_FUNC = [f.name for f in fields(Funcionario) if f.name not in ("id", "ativo")]
CAMPOS_LANC = [f.name for f in fields(Lancamento)]


def conectar(caminho: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(caminho or caminho_padrao())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(ESQUEMA)
    for tabela, coluna, ddl in MIGRACOES:
        existentes = {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}
        if coluna not in existentes:
            con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {ddl}")
            if ajuste := AJUSTES_MIGRACAO.get((tabela, coluna)):
                con.execute(ajuste)
    con.commit()
    return con


def _para_banco(v):
    return str(v) if isinstance(v, D) else v


def _func_de_linha(r: sqlite3.Row) -> Funcionario:
    dados = {}
    for f in fields(Funcionario):
        v = r[f.name]
        if f.type is D:
            v = D(v)
        elif f.type is bool:
            v = bool(v)
        elif f.type is str:
            v = v or ""
        dados[f.name] = v
    return Funcionario(**dados)


def inserir_funcionario(con, f: Funcionario) -> int:
    valores = [_para_banco(getattr(f, c)) for c in CAMPOS_FUNC]
    valores[CAMPOS_FUNC.index("cpf")] = f.cpf or None  # CPF vazio não conflita no UNIQUE
    cur = con.execute(
        f"INSERT INTO funcionarios ({', '.join(CAMPOS_FUNC)}) VALUES ({', '.join('?' * len(CAMPOS_FUNC))})",
        valores,
    )
    con.commit()
    return cur.lastrowid


def atualizar_funcionario(con, f: Funcionario) -> None:
    valores = [_para_banco(getattr(f, c)) for c in CAMPOS_FUNC]
    valores[CAMPOS_FUNC.index("cpf")] = f.cpf or None
    con.execute(
        f"UPDATE funcionarios SET {', '.join(c + ' = ?' for c in CAMPOS_FUNC)} WHERE id = ?",
        [*valores, f.id],
    )
    con.commit()


def desligar_funcionario(con, func_id: int) -> None:
    con.execute("UPDATE funcionarios SET ativo = 0 WHERE id = ?", (func_id,))
    con.commit()


def listar_funcionarios(con, somente_ativos=True) -> list[Funcionario]:
    sql = "SELECT * FROM funcionarios" + (" WHERE ativo = 1" if somente_ativos else "") + " ORDER BY nome"
    return [_func_de_linha(r) for r in con.execute(sql)]


def obter_funcionario(con, func_id: int) -> Funcionario | None:
    r = con.execute("SELECT * FROM funcionarios WHERE id = ?", (func_id,)).fetchone()
    return _func_de_linha(r) if r else None


def salvar_lancamento(con, func_id: int, competencia: str, l: Lancamento) -> None:
    colunas = ["funcionario_id", "competencia", *CAMPOS_LANC]
    con.execute(
        f"INSERT OR REPLACE INTO lancamentos ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})",
        [func_id, competencia, *(str(getattr(l, c)) for c in CAMPOS_LANC)],
    )
    con.commit()


def obter_lancamento(con, func_id: int, competencia: str) -> Lancamento:
    r = con.execute(
        "SELECT * FROM lancamentos WHERE funcionario_id = ? AND competencia = ?",
        (func_id, competencia),
    ).fetchone()
    return Lancamento(**{c: D(r[c]) for c in CAMPOS_LANC}) if r else Lancamento()


def gravar_holerite(con, func_id: int, competencia: str, h: Holerite, folha: str = "mensal") -> None:
    """Substitui o resultado anterior (reprocessamento)."""
    excluir_holerite(con, func_id, competencia, folha, commit=False)
    itens = [("P", k, v) for k, v in h.proventos.items()]
    itens += [("D", k, v) for k, v in h.descontos.items()]
    itens += [("B", k, v) for k, v in h.bases.items()]
    con.executemany(
        "INSERT INTO folha_itens (funcionario_id, competencia, tipo, descricao, valor, folha)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(func_id, competencia, tipo, desc, str(valor), folha) for tipo, desc, valor in itens],
    )
    con.commit()


def excluir_holerite(con, func_id: int, competencia: str, folha: str, commit=True) -> None:
    con.execute("DELETE FROM folha_itens WHERE funcionario_id = ? AND competencia = ? AND folha = ?",
                (func_id, competencia, folha))
    if commit:
        con.commit()


def ler_holerite(con, func_id: int, competencia: str, folha: str = "mensal") -> Holerite | None:
    linhas = con.execute(
        "SELECT tipo, descricao, valor FROM folha_itens"
        " WHERE funcionario_id = ? AND competencia = ? AND folha = ? ORDER BY rowid",
        (func_id, competencia, folha),
    ).fetchall()
    if not linhas:
        return None
    h = Holerite()
    destino = {"P": h.proventos, "D": h.descontos, "B": h.bases}
    for r in linhas:
        destino[r["tipo"]][r["descricao"]] = D(r["valor"])
    return h


def holerites_da_competencia(con, competencia: str) -> list[tuple[int, str, Holerite]]:
    """Todas as folhas (mensal, férias, 13º, rescisão) da competência."""
    pares = con.execute(
        "SELECT DISTINCT funcionario_id, folha FROM folha_itens WHERE competencia = ?", (competencia,)
    ).fetchall()
    return [(r["funcionario_id"], r["folha"], ler_holerite(con, r["funcionario_id"], competencia, r["folha"]))
            for r in pares]


def media_variaveis(con, func_id: int, comp_inicio: str, comp_fim: str) -> D:
    """Média mensal de horas extras, adicional noturno, comissões e DSR nas
    folhas mensais do período (inclusive)."""
    filtro = "funcionario_id = ? AND folha = 'mensal' AND competencia BETWEEN ? AND ?"
    meses = con.execute(f"SELECT COUNT(DISTINCT competencia) FROM folha_itens WHERE {filtro}",
                        (func_id, comp_inicio, comp_fim)).fetchone()[0]
    if not meses:
        return ZERO
    marcadores = ", ".join("?" * len(VARIAVEIS))
    valores = con.execute(
        f"SELECT valor FROM folha_itens WHERE {filtro} AND tipo = 'P' AND descricao IN ({marcadores})",
        (func_id, comp_inicio, comp_fim, *VARIAVEIS),
    ).fetchall()
    return arred(sum((D(r["valor"]) for r in valores), ZERO) / meses)


def total_pago(con, func_id: int, folha: str, ano: int) -> D:
    """Soma dos proventos de um tipo de folha no ano (ex.: 1ª parcela do 13º)."""
    valores = con.execute(
        "SELECT valor FROM folha_itens WHERE funcionario_id = ? AND folha = ? AND tipo = 'P'"
        " AND competencia LIKE ?", (func_id, folha, f"{ano}-%"),
    ).fetchall()
    return sum((D(r["valor"]) for r in valores), ZERO)
