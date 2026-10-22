"""13º salário (Lei 4.090/1962): 1ª parcela até 30/11, 2ª até 20/12."""
from decimal import Decimal as D

from . import tabelas as t
from .calculo import ZERO, Funcionario, Holerite, arred, calcular_inss, calcular_irrf, remuneracao_fixa


def valor_integral(func: Funcionario, avos: int, media_variaveis: D = ZERO) -> D:
    return arred((remuneracao_fixa(func) + media_variaveis) * avos / 12)


def irrf_13(valor: D, inss: D, func: Funcionario) -> D:
    """Tributação exclusiva: sem desconto simplificado."""
    return calcular_irrf(valor, inss, func.dependentes, func.pensao,
                         simplificado=False, reducao=t.REDUCAO_IR_APLICA_13)


def primeira_parcela(func: Funcionario, avos: int, media_variaveis: D = ZERO) -> Holerite:
    """Metade do 13º, sem descontos de INSS e IRRF (incidem só na 2ª parcela)."""
    h = Holerite()
    valor = arred(valor_integral(func, avos, media_variaveis) / 2)
    h.proventos[f"13º salário 1ª parcela ({avos}/12)"] = valor
    h.bases["Base FGTS"] = valor
    h.bases["FGTS"] = arred(valor * t.ALIQUOTA_FGTS)
    return h


def segunda_parcela(func: Funcionario, avos: int, media_variaveis: D = ZERO,
                    primeira_paga: D | None = None) -> Holerite:
    h = Holerite()
    total = valor_integral(func, avos, media_variaveis)
    if primeira_paga is None:
        primeira_paga = arred(total / 2)
    h.proventos[f"13º salário ({avos}/12)"] = total

    inss = calcular_inss(total)
    if primeira_paga:
        h.descontos["Adiantamento 13º (1ª parcela)"] = primeira_paga
    h.descontos["INSS 13º"] = inss
    if irrf := irrf_13(total, inss, func):
        h.descontos["IRRF 13º"] = irrf
    if func.pensao:
        h.descontos["Pensão alimentícia"] = arred(func.pensao)

    # O FGTS da 1ª parcela já foi recolhido em novembro
    h.bases["Base INSS"] = total
    h.bases["Base FGTS"] = total - primeira_paga
    if media_variaveis:
        h.bases["Média de variáveis"] = arred(media_variaveis)
    h.bases["FGTS"] = arred(h.base_fgts * t.ALIQUOTA_FGTS)
    return h
