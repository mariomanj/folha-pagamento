"""Operações de folha usadas pela linha de comando e pela interface gráfica.
Combinam os cálculos com o banco; não imprimem nada."""
from datetime import date
from decimal import Decimal as D

from . import banco
from .calculo import ZERO, Funcionario, Holerite, calcular_folha, valor_adiantamento
from .datas import avos_13, somar_meses
from .decimo_terceiro import primeira_parcela, segunda_parcela
from .encargos import custo_mensal, totais_guias
from .ferias import calcular_ferias
from .rescisao import MOTIVOS, calcular_rescisao

Resultado = list[tuple[Funcionario, Holerite]]


def somar_competencia(comp: str, meses: int) -> str:
    d = somar_meses(date.fromisoformat(comp + "-01"), meses)
    return f"{d.year}-{d.month:02d}"


def _media(con, func_id: int, comp_inicio: str, comp_fim: str, media: D | None) -> D:
    """Média informada ou calculada pelas folhas mensais gravadas."""
    return media if media is not None else banco.media_variaveis(con, func_id, comp_inicio, comp_fim)


def processar_mensal(con, comp: str) -> Resultado:
    resultados = []
    for f in banco.listar_funcionarios(con):
        ferias = banco.ler_holerite(con, f.id, comp, "ferias")
        h = calcular_folha(
            f, banco.obter_lancamento(con, f.id, comp), comp,
            base_inss_ferias=ferias.base_inss if ferias else ZERO,
            inss_ferias=ferias.descontos.get("INSS", ZERO) if ferias else ZERO,
        )
        banco.gravar_holerite(con, f.id, comp, h)
        resultados.append((f, h))
    return resultados


def adiantamentos(con) -> list[tuple[Funcionario, D]]:
    return [(f, valor_adiantamento(f)) for f in banco.listar_funcionarios(con) if f.adiantamento_pct]


def registrar_ferias(con, f: Funcionario, comp: str, dias: int, abono: int = 0,
                     media: D | None = None) -> Holerite:
    """Calcula o recibo (média dos 12 meses anteriores) e lança os dias de
    férias na competência para o salário do mês ficar proporcional."""
    media = _media(con, f.id, somar_competencia(comp, -12), somar_competencia(comp, -1), media)
    h = calcular_ferias(f, dias, abono, media)
    banco.gravar_holerite(con, f.id, comp, h, "ferias")
    l = banco.obter_lancamento(con, f.id, comp)
    l.dias_ferias = D(dias)
    banco.salvar_lancamento(con, f.id, comp, l)
    return h


def competencia_13(ano: int, parcela: int) -> str:
    return f"{ano}-{'11' if parcela == 1 else '12'}"


def processar_decimo(con, ano: int, parcela: int, comp: str | None = None,
                     media: D | None = None) -> tuple[str, Resultado]:
    folha = f"13-{parcela}"
    comp = comp or competencia_13(ano, parcela)
    resultados = []
    for f in banco.listar_funcionarios(con):
        admissao = date.fromisoformat(f.admissao) if f.admissao else date(ano, 1, 1)
        avos = avos_13(admissao, date(ano, 12, 31), ano)
        if not avos:
            continue
        # Média até outubro para a 1ª parcela e até novembro para a 2ª
        m = _media(con, f.id, f"{ano}-01", f"{ano}-{'10' if parcela == 1 else '11'}", media)
        if parcela == 1:
            h = primeira_parcela(f, avos, m)
        else:
            h = segunda_parcela(f, avos, m, banco.total_pago(con, f.id, "13-1", ano))
        banco.gravar_holerite(con, f.id, comp, h, folha)
        resultados.append((f, h))
    return comp, resultados


def registrar_rescisao(con, f: Funcionario, desligamento: date, motivo: str, aviso: str | None = None,
                       ferias_vencidas: int = 0, saldo_fgts: D = ZERO, media: D | None = None,
                       adiantamento_pago: D | None = None) -> tuple[Holerite, date, str]:
    """Calcula, grava, apaga a folha mensal do mês (substituída pelo saldo de
    salário) e desliga o funcionário. Retorna recibo, data projetada e competência."""
    if not f.admissao:
        raise ValueError("cadastre a data de admissão antes de calcular a rescisão")
    comp = f"{desligamento.year}-{desligamento.month:02d}"
    media = _media(con, f.id, somar_competencia(comp, -12), somar_competencia(comp, -1), media)
    if adiantamento_pago is None:
        adiantamento_pago = valor_adiantamento(f) if desligamento.day > 15 else ZERO
    h, projecao = calcular_rescisao(
        f, date.fromisoformat(f.admissao), desligamento, motivo, aviso, ferias_vencidas, saldo_fgts,
        media, banco.total_pago(con, f.id, "13-1", desligamento.year), adiantamento_pago,
    )
    banco.gravar_holerite(con, f.id, comp, h, "rescisao")
    banco.excluir_holerite(con, f.id, comp, "mensal")
    banco.desligar_funcionario(con, f.id)
    return h, projecao, comp


def resumo(con, comp: str, folha: str = "mensal") -> Resultado:
    return [(f, h) for f in banco.listar_funcionarios(con, somente_ativos=False)
            if (h := banco.ler_holerite(con, f.id, comp, folha))]


def encargos(con, comp: str) -> tuple[list[tuple[Funcionario, dict[str, D]]], dict[str, D]]:
    """Custos por funcionário (folha mensal) e totais das guias (todas as folhas)."""
    funcs = {f.id: f for f in banco.listar_funcionarios(con, somente_ativos=False)}
    todas = banco.holerites_da_competencia(con, comp)
    custos = [(funcs[fid], custo_mensal(funcs[fid], h)) for fid, folha, h in todas if folha == "mensal"]
    custos.sort(key=lambda par: par[0].nome)
    return custos, totais_guias([h for _, _, h in todas])


__all__ = ["MOTIVOS", "somar_competencia", "processar_mensal", "adiantamentos", "registrar_ferias",
           "competencia_13", "processar_decimo", "registrar_rescisao", "resumo", "encargos"]
