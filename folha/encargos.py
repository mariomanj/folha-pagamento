"""Encargos patronais, provisões e totais das guias."""
from decimal import Decimal as D

from . import tabelas as t
from .calculo import ZERO, Funcionario, Holerite, arred, remuneracao_fixa


def aliquotas_patronais() -> dict[str, D]:
    if t.EMPRESA_SIMPLES_NACIONAL:
        return {}
    return {
        "INSS patronal": t.ALIQUOTA_INSS_PATRONAL,
        "RAT": t.ALIQUOTA_RAT * t.FAP,
        "Terceiros": t.ALIQUOTA_TERCEIROS,
    }


def custo_mensal(func: Funcionario, h: Holerite) -> dict[str, D]:
    """Custo do funcionário na competência: folha mensal + encargos + provisões
    de férias e 13º (com os encargos sobre elas)."""
    c = {"Remuneração": h.total_proventos - h.proventos.get("Salário-família", ZERO)
         - h.descontos.get("Faltas", ZERO)}
    for nome, aliq in aliquotas_patronais().items():
        c[nome] = arred(h.base_inss * aliq)
    c["FGTS"] = h.fgts

    rem = remuneracao_fixa(func)
    c["Prov. 13º"] = arred(rem / 12)
    c["Prov. férias"] = arred(rem / 12 * 4 / 3)  # inclui o 1/3
    aliq_total = sum(aliquotas_patronais().values(), ZERO) + t.ALIQUOTA_FGTS
    c["Enc. provisões"] = arred((c["Prov. 13º"] + c["Prov. férias"]) * aliq_total)
    c["Custo total"] = sum(c.values(), ZERO)
    return c


def totais_guias(holerites: list[Holerite]) -> dict[str, D]:
    """Valores a recolher na competência, somando todas as folhas
    (mensal, férias, 13º e rescisões)."""
    base = sum((h.base_inss for h in holerites), ZERO)
    segurados = sum((v for h in holerites for k, v in h.descontos.items() if k.startswith("INSS")), ZERO)
    empresa = sum((arred(base * a) for a in aliquotas_patronais().values()), ZERO)
    sal_familia = sum((h.proventos.get("Salário-família", ZERO) for h in holerites), ZERO)
    multas = sum((v for h in holerites for k, v in h.bases.items() if k.startswith("Multa FGTS")), ZERO)
    return {
        "Base de cálculo INSS": base,
        "INSS segurados (descontado)": segurados,
        "INSS empresa (patronal + RAT + terceiros)": empresa,
        "(-) Salário-família a compensar": -sal_familia,
        "Total DCTFWeb (previdência)": segurados + empresa - sal_familia,
        "IRRF retido (DCTFWeb)": sum((v for h in holerites for k, v in h.descontos.items()
                                     if k.startswith("IRRF")), ZERO),
        "FGTS mensal (FGTS Digital)": sum((h.fgts for h in holerites), ZERO),
        "Multas rescisórias FGTS": multas,
    }
