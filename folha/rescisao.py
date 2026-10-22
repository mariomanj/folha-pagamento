"""Verbas rescisórias (TRCT)."""
from datetime import date, timedelta
from decimal import Decimal as D

from . import tabelas as t
from .calculo import (ZERO, Funcionario, Holerite, adicional_fixo, arred, calcular_inss,
                      calcular_irrf, remuneracao_fixa)
from .datas import anos_completos, avos_13, avos_ferias, inicio_periodo_aquisitivo, ultimo_dia
from .decimo_terceiro import irrf_13

# motivo -> modalidades de aviso prévio aceitas (a primeira é o padrão)
MOTIVOS = {
    "sem_justa_causa": ("indenizado", "trabalhado"),
    "acordo": ("indenizado", "trabalhado"),              # CLT art. 484-A
    "pedido_demissao": ("trabalhado", "nao_cumprido", "dispensado"),
    "justa_causa": ("nenhum",),
}


def dias_aviso_previo(admissao: date, desligamento: date) -> int:
    dias = t.AVISO_DIAS_BASE + t.AVISO_DIAS_POR_ANO * anos_completos(admissao, desligamento)
    return min(dias, t.AVISO_DIAS_MAXIMO)


def calcular_rescisao(func: Funcionario, admissao: date, desligamento: date, motivo: str,
                      aviso: str | None = None, ferias_vencidas: int = 0, saldo_fgts: D = ZERO,
                      media_variaveis: D = ZERO, primeira_13_paga: D = ZERO,
                      adiantamento_pago: D = ZERO) -> tuple[Holerite, date]:
    """Retorna o termo de rescisão e a data projetada pelo aviso prévio indenizado.

    `ferias_vencidas`: períodos aquisitivos completos ainda não gozados.
    `saldo_fgts`: saldo da conta vinculada, para calcular a multa rescisória."""
    if motivo not in MOTIVOS:
        raise ValueError(f"motivo inválido; use: {', '.join(MOTIVOS)}")
    aviso = aviso or MOTIVOS[motivo][0]
    if aviso not in MOTIVOS[motivo]:
        raise ValueError(f"para {motivo} o aviso deve ser: {', '.join(MOTIVOS[motivo])}")
    if desligamento < admissao:
        raise ValueError("data de desligamento anterior à admissão")

    h = Holerite()
    remuneracao = remuneracao_fixa(func) + media_variaveis
    valor_dia = remuneracao / t.DIAS_MES_COMERCIAL

    # Saldo de salário (mês comercial de 30 dias)
    ultimo = ultimo_dia(desligamento.year, desligamento.month)
    dias_saldo = 30 if desligamento.day == ultimo else min(desligamento.day, 30)
    h.proventos[f"Saldo de salário ({dias_saldo} dias)"] = arred(func.salario / 30 * dias_saldo)
    if adicional := adicional_fixo(func):
        h.proventos[f"{adicional[0]} ({dias_saldo} dias)"] = arred(adicional[1] / 30 * dias_saldo)
    base_mensal = h.total_proventos

    # Aviso prévio: o indenizado projeta o contrato para 13º e férias
    dias_indenizados = 0
    aviso_indenizado = ZERO
    if motivo in ("sem_justa_causa", "acordo"):
        total_aviso = dias_aviso_previo(admissao, desligamento)
        # Trabalhado: cumprem-se 30 dias e o acréscimo da Lei 12.506 é indenizado
        dias_indenizados = total_aviso if aviso == "indenizado" else total_aviso - 30
        if dias_indenizados:
            fator = D("0.5") if motivo == "acordo" else D("1")
            aviso_indenizado = arred(valor_dia * dias_indenizados * fator)
            h.proventos[f"Aviso prévio indenizado ({dias_indenizados} dias)"] = aviso_indenizado
    elif aviso == "nao_cumprido":
        h.descontos["Aviso prévio não cumprido (30 dias)"] = arred(valor_dia * 30)
    projecao = desligamento + timedelta(days=dias_indenizados)

    decimo = ZERO
    if motivo != "justa_causa":
        avos = sum(avos_13(admissao, projecao, ano) for ano in range(desligamento.year, projecao.year + 1))
        if avos:
            decimo = arred(remuneracao * avos / 12)
            h.proventos[f"13º salário proporcional ({avos}/12)"] = decimo

    if ferias_vencidas:
        vencidas = arred(remuneracao * ferias_vencidas)
        h.proventos[f"Férias vencidas ({ferias_vencidas} período(s))"] = vencidas
        h.proventos["1/3 sobre férias vencidas"] = arred(vencidas / 3)
    if motivo != "justa_causa":
        avos_f = avos_ferias(inicio_periodo_aquisitivo(admissao, projecao), projecao)
        if avos_f:
            proporcionais = arred(remuneracao * avos_f / 12)
            h.proventos[f"Férias proporcionais ({avos_f}/12)"] = proporcionais
            h.proventos["1/3 sobre férias proporcionais"] = arred(proporcionais / 3)

    # Tributos: saldo de salário e 13º separados; aviso indenizado e férias
    # indenizadas são isentos de INSS e IRRF
    inss = calcular_inss(base_mensal)
    h.descontos["INSS"] = inss
    if irrf := calcular_irrf(base_mensal, inss, func.dependentes, func.pensao):
        h.descontos["IRRF"] = irrf
    if decimo:
        inss13 = calcular_inss(decimo)
        h.descontos["INSS 13º"] = inss13
        if irrf := irrf_13(decimo, inss13, func):
            h.descontos["IRRF 13º"] = irrf
    if adiantamento_pago:
        h.descontos["Adiantamento salarial"] = arred(adiantamento_pago)
    if primeira_13_paga:
        h.descontos["Adiantamento 13º (1ª parcela)"] = arred(primeira_13_paga)
    if func.pensao:
        h.descontos["Pensão alimentícia"] = arred(func.pensao)

    h.bases["Base INSS"] = base_mensal + decimo
    h.bases["Base FGTS"] = base_mensal + aviso_indenizado + decimo - primeira_13_paga
    h.bases["FGTS"] = fgts = arred(h.base_fgts * t.ALIQUOTA_FGTS)
    if motivo in t.MULTA_FGTS:
        pct = t.MULTA_FGTS[motivo]
        h.bases[f"Multa FGTS {int(pct * 100)}% (guia rescisória)"] = arred((saldo_fgts + fgts) * pct)
    return h, projecao
