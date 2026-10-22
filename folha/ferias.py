"""Recibo de férias (CLT arts. 129 a 145)."""
from decimal import Decimal as D

from . import tabelas as t
from .calculo import ZERO, Funcionario, Holerite, arred, calcular_inss, calcular_irrf, remuneracao_fixa


def calcular_ferias(func: Funcionario, dias: int = 30, abono: int = 0, media_variaveis: D = ZERO) -> Holerite:
    """`dias` de gozo e `abono` dias vendidos (abono pecuniário, até 1/3 do período).
    `media_variaveis` é a média mensal de horas extras, comissões etc. do período."""
    if not 5 <= dias <= 30:
        raise ValueError("as férias devem ter entre 5 e 30 dias de gozo")
    if not 0 <= abono <= 10 or dias + abono > 30:
        raise ValueError("abono pecuniário de até 10 dias, e gozo + abono no máximo 30")

    valor_dia = (remuneracao_fixa(func) + media_variaveis) / t.DIAS_MES_COMERCIAL
    h = Holerite()
    ferias = arred(valor_dia * dias)
    terco = arred(ferias / 3)
    h.proventos[f"Férias ({dias} dias)"] = ferias
    h.proventos["1/3 constitucional de férias"] = terco
    if abono:
        valor_abono = arred(valor_dia * abono)
        h.proventos[f"Abono pecuniário ({abono} dias)"] = valor_abono
        h.proventos["1/3 sobre abono pecuniário"] = arred(valor_abono / 3)

    # Abono pecuniário e seu terço não sofrem INSS, IRRF nem FGTS
    base = ferias + terco
    inss = calcular_inss(base)
    h.descontos["INSS"] = inss
    if irrf := calcular_irrf(base, inss, func.dependentes):
        h.descontos["IRRF"] = irrf

    h.bases["Base INSS"] = h.bases["Base FGTS"] = base
    if media_variaveis:
        h.bases["Média de variáveis"] = arred(media_variaveis)
    h.bases["FGTS"] = arred(base * t.ALIQUOTA_FGTS)
    return h
