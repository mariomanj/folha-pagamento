"""Tabela de rubricas (S-1010) e associação com os itens dos recibos.

Os códigos de natureza (natRubr) vêm da Tabela 03 do eSocial e as incidências
das listas oficiais de codIncCP, codIncIRRF (Tabela 21) e codIncFGTS. O contador
deve revisá-las: ficam em rubricas.json na pasta de dados e podem ser editadas.
"""
import json
from dataclasses import asdict, dataclass

from ..config import pasta_dados

ARQUIVO = "rubricas.json"


@dataclass
class Rubrica:
    codigo: str          # codRubr
    descricao: str       # dscRubr
    natureza: int        # natRubr (Tabela 03)
    tipo: int            # tpRubr: 1 provento, 2 desconto, 3 informativa, 4 informativa dedutora
    inc_cp: str          # codIncCP
    inc_irrf: str        # codIncIRRF (Tabela 21)
    inc_fgts: str        # codIncFGTS
    folha: str           # tipo de recibo em que aparece: mensal ou ferias
    prefixos: list[str]  # início da descrição do item no recibo


PADRAO = [
    # --- folha mensal: proventos
    Rubrica("1000", "Salário", 1000, 1, "11", "11", "11", "mensal", ["Salário base", "Salário ("]),
    Rubrica("1010", "Adicional de insalubridade", 1202, 1, "11", "11", "11", "mensal", ["Adicional de insalubridade"]),
    Rubrica("1011", "Adicional de periculosidade", 1203, 1, "11", "11", "11", "mensal", ["Adicional de periculosidade"]),
    Rubrica("1020", "Horas extras 50%", 1003, 1, "11", "11", "11", "mensal", ["Horas extras 50%"]),
    Rubrica("1021", "Horas extras 100%", 1003, 1, "11", "11", "11", "mensal", ["Horas extras 100%"]),
    Rubrica("1022", "Adicional noturno", 1205, 1, "11", "11", "11", "mensal", ["Adicional noturno"]),
    Rubrica("1023", "Comissões", 1207, 1, "11", "11", "11", "mensal", ["Comissões"]),
    Rubrica("1024", "DSR sobre horas extras, adicional noturno e comissões", 1002, 1, "11", "11", "11",
            "mensal", ["DSR sobre variáveis"]),
    Rubrica("1090", "Outros proventos", 1099, 1, "11", "11", "11", "mensal", ["Outros proventos"]),
    Rubrica("1100", "Salário-família", 1409, 1, "51", "79", "00", "mensal", ["Salário-família"]),
    # --- folha mensal: descontos
    Rubrica("9000", "Faltas", 9207, 2, "11", "11", "11", "mensal", ["Faltas"]),
    Rubrica("9001", "INSS", 9201, 2, "31", "41", "00", "mensal", ["INSS"]),
    Rubrica("9002", "IRRF", 9203, 2, "00", "31", "00", "mensal", ["IRRF"]),
    Rubrica("9005", "Pensão alimentícia", 9213, 2, "00", "51", "00", "mensal", ["Pensão alimentícia"]),
    Rubrica("9006", "Vale-transporte", 9216, 2, "00", "9", "00", "mensal", ["Vale-transporte"]),
    Rubrica("9007", "Vale-refeição (PAT)", 9241, 2, "00", "9", "00", "mensal", ["Vale-refeição"]),
    Rubrica("9008", "Adiantamento salarial", 9200, 2, "00", "9", "00", "mensal", ["Adiantamento salarial"]),
    Rubrica("9010", "Plano de saúde", 9219, 2, "00", "9", "00", "mensal", ["Plano de saúde"]),
    Rubrica("9011", "Plano odontológico", 9219, 2, "00", "9", "00", "mensal", ["Plano odontológico"]),
    Rubrica("9012", "Vale-alimentação (PAT)", 9241, 2, "00", "9", "00", "mensal", ["Vale-alimentação"]),
    Rubrica("9013", "Seguro de vida", 9250, 2, "00", "9", "00", "mensal", ["Seguro de vida"]),
    Rubrica("9014", "Empréstimo consignado", 9253, 2, "00", "9", "00", "mensal", ["Empréstimo consignado"]),
    Rubrica("9015", "Contribuição sindical", 9230, 2, "00", "9", "00", "mensal", ["Contribuição sindical"]),
    Rubrica("9016", "Convênio farmácia", 9299, 2, "00", "9", "00", "mensal", ["Convênio farmácia"]),
    Rubrica("9099", "Outros descontos", 9299, 2, "00", "9", "00", "mensal", ["Outros descontos"]),
    # --- recibo de férias
    Rubrica("1200", "Férias", 1016, 1, "11", "13", "11", "ferias", ["Férias ("]),
    Rubrica("1201", "1/3 constitucional de férias", 1017, 1, "11", "13", "11", "ferias", ["1/3 constitucional"]),
    Rubrica("1202", "Abono pecuniário de férias", 1023, 1, "00", "75", "00", "ferias", ["Abono pecuniário"]),
    Rubrica("1203", "1/3 sobre abono pecuniário", 1023, 1, "00", "75", "00", "ferias", ["1/3 sobre abono"]),
    Rubrica("9003", "INSS sobre férias", 9201, 2, "31", "43", "00", "ferias", ["INSS"]),
    Rubrica("9004", "IRRF sobre férias", 9203, 2, "00", "33", "00", "ferias", ["IRRF"]),
]


def caminho():
    return pasta_dados() / ARQUIVO


def carregar() -> list[Rubrica]:
    """Lê rubricas.json; cria o arquivo com a tabela padrão se não existir e
    acrescenta as rubricas padrão criadas depois (as já gravadas não mudam)."""
    arq = caminho()
    if not arq.exists():
        salvar(PADRAO)
        return list(PADRAO)
    dados = json.loads(arq.read_text(encoding="utf-8"))
    rubricas = [Rubrica(**r) for r in dados["rubricas"]]
    codigos = {r.codigo for r in rubricas}
    if novas := [r for r in PADRAO if r.codigo not in codigos]:
        rubricas += novas
        salvar(rubricas)
    return rubricas


def salvar(rubricas: list[Rubrica]) -> None:
    dados = {"_LEIA-ME": "Rubricas enviadas ao eSocial (S-1010). Revise com o contador. Depois de enviar, "
                         "alterações exigem novo envio do S-1010 (botão Gerar eventos).",
             "rubricas": [asdict(r) for r in rubricas]}
    caminho().write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")


def rubrica_do_item(rubricas: list[Rubrica], folha: str, descricao: str) -> Rubrica:
    for r in rubricas:
        if r.folha == folha and any(descricao.startswith(p) for p in r.prefixos):
            return r
    raise ValueError(f"nenhuma rubrica do eSocial para '{descricao}' (folha {folha}); "
                     f"inclua-a em {ARQUIVO}")
