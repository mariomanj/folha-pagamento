"""Ciclo mensal do eSocial: gerar os eventos da competência, transmitir por
etapas (S-1010 → S-1200 → S-1210 → S-1299) e consultar os retornos."""
import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal as D, InvalidOperation
from pathlib import Path

from .. import banco, tabelas
from ..calculo import ZERO, Funcionario
from . import assinatura, eventos as ev, rubricas as rb, validacao, webservice as ws

ESQUEMA = """
CREATE TABLE IF NOT EXISTS esocial_eventos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo           TEXT NOT NULL,             -- S-1010, S-1200, S-1210, S-1299
    chave          TEXT NOT NULL,             -- identifica o registro no eSocial (para retificar)
    competencia    TEXT NOT NULL,             -- perApur (ou iniValid no S-1010)
    funcionario_id INTEGER,
    id_evento      TEXT NOT NULL,
    ambiente       INTEGER NOT NULL,
    xml            TEXT NOT NULL,             -- sem assinatura até o envio; assinado depois
    conteudo       TEXT NOT NULL,             -- hash dos dados, para não reenviar o que não mudou
    status         TEXT NOT NULL,             -- gerado, enviado, aceito, rejeitado
    protocolo      TEXT,
    recibo         TEXT,
    mensagens      TEXT,
    atualizado     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datas_pagamento (
    competencia TEXT NOT NULL,
    folha       TEXT NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (competencia, folha)
);
CREATE TABLE IF NOT EXISTS pagamentos_externos (   -- folhas do sistema anterior pagas neste programa
    cpf        TEXT NOT NULL,
    data       TEXT NOT NULL,
    per_ref    TEXT NOT NULL,
    ide_dm_dev TEXT NOT NULL,
    valor      TEXT NOT NULL,
    PRIMARY KEY (cpf, per_ref, ide_dm_dev)
);
"""
ETAPAS = ("S-1010", "S-1200", "S-1210", "S-1299")
DEMONSTRATIVOS = {"mensal": "M", "ferias": "F"}  # folhas enviadas no S-1200


def preparar(con) -> None:
    con.executescript(ESQUEMA)


def ide_dm_dev(competencia: str, folha: str) -> str:
    return f"FP{competencia.replace('-', '')}{DEMONSTRATIVOS[folha]}"


def _hash(*partes) -> str:
    return hashlib.sha256(json.dumps(partes, default=str, sort_keys=True).encode()).hexdigest()


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def empregador() -> ev.Empregador:
    cnpj = ev.somente_digitos(tabelas.EMPRESA_CNPJ)
    estab = ev.somente_digitos(tabelas.ESOCIAL_CNPJ_ESTABELECIMENTO) or cnpj
    problemas = []
    if not ev.cnpj_valido(cnpj):
        problemas.append("CNPJ da empresa inválido ou não informado")
    if estab != cnpj and not ev.cnpj_valido(estab):
        problemas.append("CNPJ do estabelecimento inválido")
    if not str(tabelas.ESOCIAL_COD_LOTACAO).strip():
        problemas.append("código da lotação tributária (o mesmo do S-1020 já enviado) não informado")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(tabelas.ESOCIAL_INICIO_RUBRICAS)):
        problemas.append("competência inicial das rubricas não informada")
    if tabelas.ESOCIAL_AMBIENTE not in (1, 2):
        problemas.append("ambiente deve ser 1 (produção) ou 2 (produção restrita)")
    if problemas:
        raise ValueError("Complete a configuração do eSocial (aba Configurações):\n- " + "\n- ".join(problemas))
    return ev.Empregador(cnpj, estab, str(tabelas.ESOCIAL_COD_LOTACAO).strip(),
                         str(tabelas.ESOCIAL_TAB_RUBRICAS).strip() or "FOLHA", int(tabelas.ESOCIAL_AMBIENTE))


def problemas_trabalhador(f: Funcionario) -> list[str]:
    p = []
    if not ev.cpf_valido(f.cpf):
        p.append("CPF inválido ou não informado")
    if not f.matricula_esocial.strip():
        p.append("matrícula do eSocial não informada")
    if not 100 <= f.categoria <= 999:
        p.append("categoria do eSocial inválida")
    return p


# --- consulta ao histórico -------------------------------------------------------

def _ultimo_aceito(con, chave: str, ambiente: int):
    return con.execute("SELECT * FROM esocial_eventos WHERE chave = ? AND ambiente = ? AND status = 'aceito'"
                       " ORDER BY id DESC LIMIT 1", (chave, ambiente)).fetchone()


def _precisa_gerar(con, chave: str, conteudo: str, ambiente: int) -> bool:
    """Falso se o mesmo conteúdo já foi aceito ou já está gerado/enviado."""
    r = con.execute("SELECT status, conteudo FROM esocial_eventos WHERE chave = ? AND ambiente = ?"
                    " AND status IN ('aceito', 'gerado', 'enviado') ORDER BY id DESC LIMIT 1",
                    (chave, ambiente)).fetchone()
    return not (r and r["conteudo"] == conteudo)


def _registrar(con, tipo, chave, competencia, funcionario_id, id_evento, xml, conteudo, ambiente):
    """Confere a estrutura (com assinatura de teste) e grava o evento como
    'gerado', substituindo uma versão anterior ainda não aceita."""
    erros = validacao.erros(tipo, assinatura.assinar(xml, assinatura.certificado_teste()))
    if erros:
        raise ValueError(f"{tipo} ({chave}) não passou na validação do esquema oficial:\n" + "\n".join(erros[:5]))
    con.execute("DELETE FROM esocial_eventos WHERE chave = ? AND ambiente = ? AND status IN ('gerado', 'rejeitado')",
                (chave, ambiente))
    con.execute(
        "INSERT INTO esocial_eventos (tipo, chave, competencia, funcionario_id, id_evento, ambiente, xml, conteudo,"
        " status, atualizado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'gerado', ?)",
        (tipo, chave, competencia, funcionario_id, id_evento, ambiente, xml.decode(), conteudo, _agora()))


# --- geração ---------------------------------------------------------------------

@dataclass
class ResultadoGeracao:
    gerados: dict[str, int] = field(default_factory=lambda: dict.fromkeys(ETAPAS, 0))
    avisos: list[str] = field(default_factory=list)


def gerar(con, comp: str) -> ResultadoGeracao:
    preparar(con)
    emp = empregador()
    amb = emp.ambiente
    if con.execute("SELECT 1 FROM esocial_eventos WHERE status = 'enviado' AND ambiente = ?"
                   " AND (competencia = ? OR tipo = 'S-1010')", (amb, comp)).fetchone():
        raise ValueError("Há eventos enviados aguardando o retorno do eSocial. "
                         "Clique em 'Consultar retornos' antes de gerar de novo.")
    g = ev.Gerador(emp)
    res = ResultadoGeracao()
    if _ultimo_aceito(con, f"S-1299|{comp}", amb):
        res.avisos.append(f"O período {comp} já foi fechado (S-1299 aceito). Alterações só serão aceitas "
                          "depois de reabrir o período no eSocial (S-1298).")

    # S-1010: inclusão na primeira vez; alteração se a rubrica mudou depois de aceita
    lista_rubricas = rb.carregar()
    for r in lista_rubricas:
        chave = f"S-1010|{emp.tab_rubricas}|{r.codigo}"
        conteudo = _hash(r.descricao, r.natureza, r.tipo, r.inc_cp, r.inc_irrf, r.inc_fgts)
        if not _precisa_gerar(con, chave, conteudo, amb):
            continue
        aceito = _ultimo_aceito(con, chave, amb)
        ini_valid = aceito["competencia"] if aceito else tabelas.ESOCIAL_INICIO_RUBRICAS
        id_evento, xml = g.s1010(r, ini_valid, alteracao=bool(aceito))
        _registrar(con, "S-1010", chave, ini_valid, None, id_evento, xml, conteudo, amb)
        res.gerados["S-1010"] += 1

    funcs = banco.listar_funcionarios(con, somente_ativos=False)

    # S-1200: folha mensal e recibo de férias da competência
    for f in funcs:
        if banco.ler_holerite(con, f.id, comp, "rescisao"):
            res.avisos.append(f"{f.nome}: rescisão em {comp}. O S-2299 ainda não é gerado por este programa; "
                              "envie pelo sistema anterior ou pelo eSocial Web Geral.")
        demonstrativos = [(ide_dm_dev(comp, folha), folha, h) for folha in DEMONSTRATIVOS
                          if (h := banco.ler_holerite(con, f.id, comp, folha))]
        if not demonstrativos:
            continue
        if p := problemas_trabalhador(f):
            res.avisos.append(f"{f.nome}: {'; '.join(p)}. S-1200 não gerado.")
            continue
        chave = f"S-1200|{comp}|{ev.somente_digitos(f.cpf)}"
        conteudo = _hash(f.cpf, f.matricula_esocial, f.categoria, f.grau_exposicao, emp.estabelecimento,
                         emp.lotacao, [(i, folha, h.proventos, h.descontos) for i, folha, h in demonstrativos])
        if not _precisa_gerar(con, chave, conteudo, amb):
            continue
        aceito = _ultimo_aceito(con, chave, amb)
        id_evento, xml = g.s1200(f, comp, demonstrativos, lista_rubricas, aceito["recibo"] if aceito else None)
        _registrar(con, "S-1200", chave, comp, f.id, id_evento, xml, conteudo, amb)
        res.gerados["S-1200"] += 1

    # S-1210: pagamentos feitos dentro da competência (de qualquer folha anterior)
    por_cpf: dict[str, dict] = {}
    for linha in con.execute("SELECT * FROM datas_pagamento WHERE substr(data, 1, 7) = ?", (comp,)).fetchall():
        if linha["folha"] not in DEMONSTRATIVOS:
            res.avisos.append(f"Pagamento de {linha['folha']} ({linha['competencia']}) não enviado: "
                              "13º e rescisão ainda não são gerados por este programa.")
            continue
        for f in funcs:
            h = banco.ler_holerite(con, f.id, linha["competencia"], linha["folha"])
            if not h or problemas_trabalhador(f):
                continue
            cpf = ev.somente_digitos(f.cpf)
            item = por_cpf.setdefault(cpf, {"func": f, "pagamentos": [], "pensao": ZERO})
            item["pagamentos"].append((date.fromisoformat(linha["data"]), linha["competencia"],
                                       ide_dm_dev(linha["competencia"], linha["folha"]), h.liquido))
            item["pensao"] += h.descontos.get("Pensão alimentícia", ZERO)
    for linha in con.execute("SELECT * FROM pagamentos_externos WHERE substr(data, 1, 7) = ?", (comp,)).fetchall():
        item = por_cpf.setdefault(linha["cpf"], {"func": None, "pagamentos": [], "pensao": ZERO})
        item["pagamentos"].append((date.fromisoformat(linha["data"]), linha["per_ref"], linha["ide_dm_dev"],
                                   D(linha["valor"])))
    for cpf, item in sorted(por_cpf.items()):
        f = item["func"]
        pensao = None
        if item["pensao"]:
            if not ev.cpf_valido(f.cpf_pensao):
                res.avisos.append(f"{f.nome}: informe o CPF do beneficiário da pensão alimentícia. S-1210 não gerado.")
                continue
            pensao = (f.cpf_pensao, item["pensao"])
        pagamentos = sorted(item["pagamentos"])
        chave = f"S-1210|{comp}|{cpf}"
        conteudo = _hash(pagamentos, pensao)
        if not _precisa_gerar(con, chave, conteudo, amb):
            continue
        aceito = _ultimo_aceito(con, chave, amb)
        id_evento, xml = g.s1210(cpf, comp, pagamentos, pensao, aceito["recibo"] if aceito else None)
        _registrar(con, "S-1210", chave, comp, f.id if f else None, id_evento, xml, conteudo, amb)
        res.gerados["S-1210"] += 1

    # S-1299: fechamento, refeito sempre que houver remuneração ou pagamento novo
    def existe(tipo):
        return con.execute("SELECT 1 FROM esocial_eventos WHERE tipo = ? AND competencia = ? AND ambiente = ?"
                           " AND status != 'rejeitado'", (tipo, comp, amb)).fetchone() is not None

    tem_remun, tem_pgto = existe("S-1200"), existe("S-1210")
    novos = con.execute("SELECT 1 FROM esocial_eventos WHERE tipo IN ('S-1200', 'S-1210') AND competencia = ?"
                        " AND ambiente = ? AND status = 'gerado'", (comp, amb)).fetchone()
    chave = f"S-1299|{comp}"
    conteudo = _hash(tem_remun, tem_pgto)
    if (tem_remun or tem_pgto) and (novos or _precisa_gerar(con, chave, conteudo, amb)):
        id_evento, xml = g.s1299(comp, tem_remun, tem_pgto)
        _registrar(con, "S-1299", chave, comp, None, id_evento, xml, conteudo, amb)
        res.gerados["S-1299"] += 1
    con.commit()
    return res


# --- transmissão -----------------------------------------------------------------

def _filtro_etapa(etapa: str) -> str:
    return "tipo = ? AND ambiente = ?" + ("" if etapa == "S-1010" else " AND competencia = ?")


def _parametros(etapa, amb, comp):
    return (etapa, amb) if etapa == "S-1010" else (etapa, amb, comp)


def proxima_etapa(con, comp: str, amb: int) -> str | None:
    for etapa in ETAPAS:
        if con.execute(f"SELECT 1 FROM esocial_eventos WHERE {_filtro_etapa(etapa)} AND status = 'gerado'",
                       _parametros(etapa, amb, comp)).fetchone():
            return etapa
    return None


@dataclass
class ResultadoEnvio:
    etapa: str
    eventos: int
    protocolos: list[str]


def enviar(con, comp: str, certificado: assinatura.Certificado) -> ResultadoEnvio:
    """Envia a próxima etapa pendente. As etapas seguintes dependem do
    processamento desta: consulte os retornos antes de enviar de novo."""
    preparar(con)
    emp = empregador()
    amb = emp.ambiente
    if con.execute("SELECT 1 FROM esocial_eventos WHERE status = 'enviado' AND ambiente = ?", (amb,)).fetchone():
        raise ValueError("Há lotes aguardando processamento. Clique em 'Consultar retornos' antes de enviar.")
    etapa = proxima_etapa(con, comp, amb)
    if not etapa:
        raise ValueError("Nenhum evento pendente de envio. Clique em 'Gerar eventos' primeiro.")
    for anterior in ETAPAS[:ETAPAS.index(etapa)]:
        if con.execute(f"SELECT 1 FROM esocial_eventos WHERE {_filtro_etapa(anterior)} AND status = 'rejeitado'",
                       _parametros(anterior, amb, comp)).fetchone():
            raise ValueError(f"Há eventos {anterior} rejeitados. Corrija-os e gere de novo antes de enviar {etapa}.")
    linhas = con.execute(f"SELECT * FROM esocial_eventos WHERE {_filtro_etapa(etapa)} AND status = 'gerado'"
                         " ORDER BY id", _parametros(etapa, amb, comp)).fetchall()
    transmissor = certificado.documento or emp.cnpj
    protocolos = []
    for i in range(0, len(linhas), ws.MAX_EVENTOS_LOTE):
        bloco = linhas[i:i + ws.MAX_EVENTOS_LOTE]
        assinados = [(r["id_evento"], assinatura.assinar(r["xml"].encode(), certificado)) for r in bloco]
        lote = ws.montar_lote(ws.GRUPO[etapa], emp.cnpj, transmissor, assinados)
        ret = ws.enviar_lote(lote, certificado, amb)
        if not ret.aceito:
            detalhes = "\n".join(f"- {o}" for o in ret.ocorrencias)
            raise ValueError(f"O eSocial recusou o lote ({ret.codigo} - {ret.descricao}).\n{detalhes}".strip())
        for r, (_, xml) in zip(bloco, assinados):
            con.execute("UPDATE esocial_eventos SET status = 'enviado', protocolo = ?, xml = ?, atualizado = ?"
                        " WHERE id = ?", (ret.protocolo, xml.decode(), _agora(), r["id"]))
        con.commit()  # a cada lote: o protocolo não pode se perder se o próximo falhar
        protocolos.append(ret.protocolo)
    return ResultadoEnvio(etapa, len(linhas), protocolos)


def consultar(con, certificado: assinatura.Certificado) -> list[str]:
    """Atualiza os eventos enviados com o resultado do processamento."""
    preparar(con)
    mensagens = []
    lotes = con.execute("SELECT DISTINCT protocolo, ambiente FROM esocial_eventos WHERE status = 'enviado'").fetchall()
    if not lotes:
        return ["Nenhum lote aguardando retorno."]
    for lote in lotes:
        ret = ws.consultar_lote(lote["protocolo"], certificado, lote["ambiente"])
        if ret.em_processamento:
            espera = f" (previsão: {ret.tempo_estimado} s)" if ret.tempo_estimado else ""
            mensagens.append(f"Lote {lote['protocolo']}: ainda em processamento{espera}. Consulte novamente.")
            continue
        aceitos = rejeitados = 0
        retornados = {e.id_evento: e for e in ret.eventos}
        for r in con.execute("SELECT id, id_evento FROM esocial_eventos WHERE protocolo = ? AND status = 'enviado'",
                             (lote["protocolo"],)).fetchall():
            e = retornados.get(r["id_evento"])
            if e and e.aceito:
                avisos = "\n".join(str(o) for o in e.ocorrencias)
                con.execute("UPDATE esocial_eventos SET status = 'aceito', recibo = ?, mensagens = ?, atualizado = ?"
                            " WHERE id = ?", (e.recibo, avisos, _agora(), r["id"]))
                aceitos += 1
            else:
                texto = ("\n".join(str(o) for o in e.ocorrencias) or f"{e.codigo} - {e.descricao}") if e else \
                    f"{ret.codigo} - {ret.descricao}\n" + "\n".join(str(o) for o in ret.ocorrencias)
                con.execute("UPDATE esocial_eventos SET status = 'rejeitado', mensagens = ?, atualizado = ?"
                            " WHERE id = ?", (texto.strip(), _agora(), r["id"]))
                rejeitados += 1
        con.commit()
        mensagens.append(f"Lote {lote['protocolo']}: {aceitos} aceito(s), {rejeitados} rejeitado(s).")
    return mensagens


# --- consulta, pagamentos e exportação -------------------------------------------

def listar(con, comp: str, amb: int):
    """Situação mais recente de cada registro da competência (e das rubricas)."""
    preparar(con)
    return con.execute(
        "SELECT e.*, f.nome FROM esocial_eventos e LEFT JOIN funcionarios f ON f.id = e.funcionario_id"
        " WHERE e.ambiente = ? AND (e.competencia = ? OR e.tipo = 'S-1010')"
        " AND e.id = (SELECT MAX(id) FROM esocial_eventos x WHERE x.chave = e.chave AND x.ambiente = e.ambiente)"
        " ORDER BY CASE e.tipo WHEN 'S-1200' THEN 1 WHEN 'S-1210' THEN 2 WHEN 'S-1299' THEN 3 ELSE 4 END,"
        " f.nome, e.chave", (amb, comp)).fetchall()


def definir_data_pagamento(con, comp: str, folha: str, data: date) -> None:
    preparar(con)
    con.execute("INSERT OR REPLACE INTO datas_pagamento VALUES (?, ?, ?)", (comp, folha, data.isoformat()))
    con.commit()


def data_pagamento(con, comp: str, folha: str) -> date | None:
    preparar(con)
    r = con.execute("SELECT data FROM datas_pagamento WHERE competencia = ? AND folha = ?", (comp, folha)).fetchone()
    return date.fromisoformat(r["data"]) if r else None


def importar_pagamentos_externos(con, caminho: Path) -> int:
    """CSV separado por ';' com cabeçalho: cpf;data;competencia;ide_dm_dev;valor
    (data DD/MM/AAAA, competência MM/AAAA, valor 1.234,56). Serve para a
    transição: pagamentos feitos neste programa de folhas do sistema anterior."""
    preparar(con)
    total = 0
    with open(caminho, encoding="utf-8-sig", newline="") as arq:
        for n, linha in enumerate(csv.DictReader(arq, delimiter=";"), start=2):
            try:
                cpf = ev.somente_digitos(linha["cpf"])
                if not ev.cpf_valido(cpf):
                    raise ValueError("CPF inválido")
                data = datetime.strptime(linha["data"].strip(), "%d/%m/%Y").date()
                mes, ano = linha["competencia"].strip().split("/")
                valor = D(linha["valor"].strip().replace(".", "").replace(",", "."))
                ide = linha["ide_dm_dev"].strip()
                if not ide:
                    raise ValueError("ide_dm_dev vazio")
            except (KeyError, ValueError, InvalidOperation) as e:
                raise ValueError(f"linha {n} do CSV: {e}") from e
            con.execute("INSERT OR REPLACE INTO pagamentos_externos VALUES (?, ?, ?, ?, ?)",
                        (cpf, data.isoformat(), f"{ano}-{int(mes):02d}", ide, str(valor)))
            total += 1
    con.commit()
    return total


def exportar_xmls(con, comp: str, amb: int, pasta: Path) -> int:
    pasta.mkdir(parents=True, exist_ok=True)
    linhas = listar(con, comp, amb)
    for r in linhas:
        (pasta / f"{r['tipo']}_{r['id_evento']}.xml").write_text(r["xml"], encoding="utf-8")
    return len(linhas)
