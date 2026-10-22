"""Saídas: recibos em texto e exportações CSV."""
import csv
from decimal import Decimal as D
from pathlib import Path

from . import tabelas as t
from .calculo import Funcionario, Holerite

TITULOS = {
    "mensal": "RECIBO DE PAGAMENTO",
    "ferias": "RECIBO DE FÉRIAS",
    "13-1": "13º SALÁRIO 1ª PARCELA",
    "13-2": "13º SALÁRIO 2ª PARCELA",
    "rescisao": "TERMO DE RESCISÃO",
}
LARGURA = 70


def numero(v: D) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def moeda(v: D) -> str:
    return "R$ " + numero(v)


def numero_csv(v: D) -> str:
    return str(v).replace(".", ",")  # vírgula decimal para o Excel em português


def holerite_texto(f: Funcionario, competencia: str, h: Holerite, folha: str = "mensal") -> str:
    empresa = [f"{t.EMPRESA_NOME}   CNPJ: {t.EMPRESA_CNPJ or '-'}"] if t.EMPRESA_NOME else []
    linhas = [
        "=" * LARGURA,
        *empresa,
        f"{TITULOS[folha]} — competência {competencia[5:]}/{competencia[:4]}".center(LARGURA),
        "=" * LARGURA,
        f"Funcionário: {f.nome}  (matrícula {f.id})",
        f"Cargo: {f.cargo or '-'}   CPF: {f.cpf or '-'}   Admissão: {f.admissao or '-'}",
        "-" * LARGURA,
        f"{'Descrição':<40}{'Proventos':>15}{'Descontos':>15}",
        "-" * LARGURA,
    ]
    for desc, v in h.proventos.items():
        linhas.append(f"{desc:<40}{moeda(v):>15}{'':>15}")
    for desc, v in h.descontos.items():
        linhas.append(f"{desc:<40}{'':>15}{moeda(v):>15}")
    linhas += [
        "-" * LARGURA,
        f"{'Totais':<40}{moeda(h.total_proventos):>15}{moeda(h.total_descontos):>15}",
        f"{'LÍQUIDO A RECEBER':<55}{moeda(h.liquido):>15}",
        "-" * LARGURA,
    ]
    linhas += [f"{desc:<55}{moeda(v):>15}" for desc, v in h.bases.items()]
    linhas.append("=" * LARGURA)
    return "\n".join(linhas)


def exportar_resumo_csv(caminho: Path, linhas: list[tuple[Funcionario, Holerite]]) -> None:
    with open(caminho, "w", newline="", encoding="utf-8-sig") as arq:
        w = csv.writer(arq, delimiter=";")  # ";" abre direto no Excel em português
        w.writerow(["Matrícula", "Nome", "Proventos", "Descontos", "INSS", "IRRF", "Líquido", "FGTS"])
        for f, h in linhas:
            inss = sum((v for k, v in h.descontos.items() if k.startswith("INSS")), D(0))
            irrf = sum((v for k, v in h.descontos.items() if k.startswith("IRRF")), D(0))
            w.writerow([f.id, f.nome, *map(numero_csv, (
                h.total_proventos, h.total_descontos, inss, irrf, h.liquido, h.fgts))])


def exportar_custos_csv(caminho: Path, linhas: list[tuple[Funcionario, dict[str, D]]]) -> None:
    colunas = list(linhas[0][1])
    with open(caminho, "w", newline="", encoding="utf-8-sig") as arq:
        w = csv.writer(arq, delimiter=";")
        w.writerow(["Matrícula", "Nome", *colunas])
        for f, custo in linhas:
            w.writerow([f.id, f.nome, *(numero_csv(custo[c]) for c in colunas)])
