"""Contagem de prazos: avos de 13º e férias, tempo de serviço."""
import calendar
from datetime import date


def ultimo_dia(ano: int, mes: int) -> int:
    return calendar.monthrange(ano, mes)[1]


def somar_meses(d: date, meses: int) -> date:
    m = d.month - 1 + meses
    ano, mes = d.year + m // 12, m % 12 + 1
    return date(ano, mes, min(d.day, ultimo_dia(ano, mes)))


def anos_completos(inicio: date, fim: date) -> int:
    anos = fim.year - inicio.year - ((fim.month, fim.day) < (inicio.month, inicio.day))
    return max(0, anos)


def avos_13(inicio: date, fim: date, ano: int) -> int:
    """Meses do ano com 15 ou mais dias trabalhados entre `inicio` e `fim`."""
    avos = 0
    for mes in range(1, 13):
        a = max(date(ano, mes, 1), inicio)
        b = min(date(ano, mes, ultimo_dia(ano, mes)), fim)
        if (b - a).days + 1 >= 15:
            avos += 1
    return avos


def avos_ferias(inicio_periodo: date, fim: date) -> int:
    """Avos do período aquisitivo: um por mês completo e mais um se a fração
    final tiver 15 dias ou mais. Máximo 12."""
    if fim < inicio_periodo:
        return 0
    meses = (fim.year - inicio_periodo.year) * 12 + fim.month - inicio_periodo.month
    while meses > 0 and somar_meses(inicio_periodo, meses) > fim:
        meses -= 1
    fracao = (fim - somar_meses(inicio_periodo, meses)).days + 1
    return min(12, meses + (1 if fracao >= 15 else 0))


def inicio_periodo_aquisitivo(admissao: date, referencia: date) -> date:
    return somar_meses(admissao, 12 * anos_completos(admissao, referencia))
