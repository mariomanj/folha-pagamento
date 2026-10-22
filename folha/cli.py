"""Interface de linha de comando:  python -m folha <comando> --help"""
import argparse
import re
import sys
from datetime import date
from decimal import Decimal as D, InvalidOperation
from pathlib import Path

from . import banco, config, servicos, tabelas
from .calculo import ZERO, Funcionario
from .relatorios import exportar_custos_csv, exportar_resumo_csv, holerite_texto, moeda, numero
from .rescisao import MOTIVOS


# --- conversores de argumentos ----------------------------------------------------

def valor(texto: str) -> D:
    """Aceita '3500', '3500.50' ou '3.500,50'."""
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return D(texto)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"valor inválido: {texto}")


def competencia(texto: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", texto):
        raise argparse.ArgumentTypeError("use o formato AAAA-MM, ex.: 2026-10")
    return texto


def data(texto: str) -> str:
    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError("use o formato AAAA-MM-DD, ex.: 2026-10-15")


def sim_nao(texto: str) -> bool:
    if texto.lower() not in ("sim", "nao", "não"):
        raise argparse.ArgumentTypeError("use sim ou nao")
    return texto.lower() == "sim"


# --- comandos ---------------------------------------------------------------------

def _funcionario(con, matricula: int) -> Funcionario:
    f = banco.obter_funcionario(con, matricula)
    if not f:
        sys.exit(f"Matrícula {matricula} não encontrada.")
    return f


def cmd_admitir(con, a):
    f = Funcionario(nome=a.nome, salario=a.salario)
    _aplicar_cadastro(f, a)
    print(f"Funcionário cadastrado com matrícula {banco.inserir_funcionario(con, f)}.")


def cmd_alterar(con, a):
    f = _funcionario(con, a.matricula)
    _aplicar_cadastro(f, a)
    banco.atualizar_funcionario(con, f)
    print("Cadastro atualizado.")


def _aplicar_cadastro(f: Funcionario, a):
    for campo in banco.CAMPOS_FUNC:
        if getattr(a, campo, None) is not None:
            setattr(f, campo, getattr(a, campo))
    if a.valor_vt and a.usa_vt is None:
        f.usa_vt = True


def cmd_listar(con, a):
    funcs = banco.listar_funcionarios(con, somente_ativos=not a.todos)
    if not funcs:
        print("Nenhum funcionário cadastrado.")
    for f in funcs:
        situacao = "" if f.ativo else " [desligado]"
        print(f"{f.id:>4}  {f.nome:<30} {f.cargo:<20} {moeda(f.salario):>14}  dep: {f.dependentes}{situacao}")


def cmd_desligar(con, a):
    banco.desligar_funcionario(con, a.matricula)
    print("Funcionário marcado como desligado (sem cálculo de verbas; use 'rescisao' para calcular).")


def cmd_lancar(con, a):
    """Atualiza só os campos informados; os demais lançamentos do mês são mantidos."""
    _funcionario(con, a.matricula)
    l = banco.obter_lancamento(con, a.matricula, a.competencia)
    for campo in banco.CAMPOS_LANC:
        if getattr(a, campo) is not None:
            setattr(l, campo, getattr(a, campo))
    banco.salvar_lancamento(con, a.matricula, a.competencia, l)
    print("Lançamento gravado. Rode 'processar' para recalcular a folha.")


def cmd_processar(con, a):
    _imprimir_resumo(f"Folha mensal {a.competencia}", servicos.processar_mensal(con, a.competencia))


def cmd_adiantamento(con, a):
    lista = servicos.adiantamentos(con)
    if not lista:
        sys.exit("Nenhum funcionário com adiantamento (cadastre com --adiantamento PERCENTUAL).")
    print(f"Adiantamento quinzenal {a.competencia}\n")
    for f, v in lista:
        print(f"{f.id:>4}  {f.nome:<30} {f.adiantamento_pct:>5}%  {moeda(v):>14}")
    print(f"{'':>4}  {'TOTAL':<38}{moeda(sum((v for _, v in lista), ZERO)):>14}")
    print("\nO valor é descontado automaticamente na folha mensal.")


def cmd_ferias(con, a):
    f = _funcionario(con, a.matricula)
    h = servicos.registrar_ferias(con, f, a.competencia, a.dias, a.abono, a.media)
    print(holerite_texto(f, a.competencia, h, "ferias"))
    print(f"\n{a.dias} dias de férias lançados em {a.competencia}: o salário do mês será proporcional.")
    print("Se o período cruzar o mês, ajuste com 'lancar --dias-ferias' em cada competência.")


def cmd_decimo(con, a):
    comp, resultados = servicos.processar_decimo(con, a.ano, a.parcela, a.competencia, a.media)
    _imprimir_resumo(f"13º salário {a.parcela}ª parcela {a.ano} (competência {comp})", resultados)


def cmd_rescisao(con, a):
    f = _funcionario(con, a.matricula)
    h, projecao, comp = servicos.registrar_rescisao(
        con, f, date.fromisoformat(a.data), a.motivo, a.aviso, a.ferias_vencidas,
        a.saldo_fgts, a.media, a.adiantamento_pago)
    print(holerite_texto(f, comp, h, "rescisao"))
    print(f"\nMotivo: {a.motivo}   Aviso: {a.aviso or MOTIVOS[a.motivo][0]}   "
          f"Data projetada: {projecao:%d/%m/%Y}")
    print("Funcionário desligado. Prazo de pagamento: 10 dias corridos (CLT art. 477 §6º).")


def cmd_holerite(con, a):
    f = _funcionario(con, a.matricula)
    h = banco.ler_holerite(con, a.matricula, a.competencia, a.folha)
    if not h:
        sys.exit("Recibo não encontrado. Processe a competência primeiro.")
    print(holerite_texto(f, a.competencia, h, a.folha))


def cmd_resumo(con, a):
    resultados = servicos.resumo(con, a.competencia, a.folha)
    if not resultados:
        sys.exit("Nada processado nessa competência para esse tipo de folha.")
    _imprimir_resumo(f"Folha {a.folha} {a.competencia}", resultados)
    if a.csv:
        exportar_resumo_csv(Path(a.csv), resultados)
        print(f"\nResumo exportado para {a.csv}")


def cmd_encargos(con, a):
    custos, guias = servicos.encargos(con, a.competencia)
    if not custos and not any(guias.values()):
        sys.exit("Competência não processada.")

    regime = "Simples Nacional" if tabelas.EMPRESA_SIMPLES_NACIONAL else "Lucro Presumido/Real"
    print(f"Custo da folha mensal {a.competencia} ({regime})\n")
    if custos:
        colunas = list(custos[0][1])
        print(f"{'Nome':<20}" + "".join(f"{c:>15}" for c in colunas))
        totais = dict.fromkeys(colunas, ZERO)
        for f, c in custos:
            print(f"{f.nome[:19]:<20}" + "".join(f"{numero(c[k]):>15}" for k in colunas))
            for k in colunas:
                totais[k] += c[k]
        print(f"{'TOTAL':<20}" + "".join(f"{numero(totais[k]):>15}" for k in colunas))

    print(f"\nGuias da competência {a.competencia} (todas as folhas)\n")
    for desc, v in guias.items():
        print(f"{desc:<45}{moeda(v):>18}")

    if a.csv and custos:
        exportar_custos_csv(Path(a.csv), custos)
        print(f"\nCustos exportados para {a.csv}")


def _imprimir_resumo(titulo, resultados):
    print(f"{titulo} — {len(resultados)} funcionário(s)\n")
    print(f"{'Mat':>4}  {'Nome':<28}{'Proventos':>15}{'Descontos':>15}{'Líquido':>15}{'FGTS':>13}")
    tp = td = tl = tf = ZERO
    for f, h in resultados:
        print(f"{f.id:>4}  {f.nome[:27]:<28}{moeda(h.total_proventos):>15}"
              f"{moeda(h.total_descontos):>15}{moeda(h.liquido):>15}{moeda(h.fgts):>13}")
        tp += h.total_proventos; td += h.total_descontos; tl += h.liquido; tf += h.fgts
    print(f"{'':>4}  {'TOTAL':<28}{moeda(tp):>15}{moeda(td):>15}{moeda(tl):>15}{moeda(tf):>13}")


# --- parser -------------------------------------------------------------------------

def _args_cadastro(s, novo: bool):
    """Opções de cadastro. Em 'alterar' nada é obrigatório e só o informado muda."""
    s.add_argument("--nome", required=novo)
    s.add_argument("--salario", type=valor, required=novo)
    s.add_argument("--cpf")
    s.add_argument("--cargo")
    s.add_argument("--admissao", type=data, help="AAAA-MM-DD")
    s.add_argument("--dependentes", type=int, help="dependentes para o IRRF")
    s.add_argument("--usa-vt", dest="usa_vt", type=sim_nao, help="sim ou nao (recebe vale-transporte)")
    s.add_argument("--vt", dest="valor_vt", type=valor, help="custo mensal do vale-transporte (marca --usa-vt sim)")
    s.add_argument("--vr", dest="desconto_vr", type=valor, help="desconto mensal do vale-refeição")
    s.add_argument("--pensao", type=valor, help="pensão alimentícia mensal")
    s.add_argument("--insalubridade", type=int, choices=tabelas.GRAUS_INSALUBRIDADE,
                   help="grau: %% sobre o salário mínimo")
    s.add_argument("--periculosidade", type=sim_nao, help="sim ou nao")
    s.add_argument("--filhos-sf", dest="filhos_sf", type=int, help="filhos até 14 anos (salário-família)")
    s.add_argument("--adiantamento", dest="adiantamento_pct", type=valor,
                   help="%% do salário pago como adiantamento quinzenal")


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="folha", description="Sistema de folha de pagamento")
    p.add_argument("--banco", help="arquivo SQLite (padrão: folha.db na pasta de dados)")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("admitir", help="cadastrar funcionário")
    _args_cadastro(s, novo=True)
    s.set_defaults(func=cmd_admitir)

    s = sub.add_parser("alterar", help="alterar cadastro (salário, dependentes etc.)")
    s.add_argument("matricula", type=int)
    _args_cadastro(s, novo=False)
    s.set_defaults(func=cmd_alterar)

    s = sub.add_parser("listar", help="listar funcionários")
    s.add_argument("--todos", action="store_true", help="incluir desligados")
    s.set_defaults(func=cmd_listar)

    s = sub.add_parser("desligar", help="desligar sem calcular verbas")
    s.add_argument("matricula", type=int)
    s.set_defaults(func=cmd_desligar)

    s = sub.add_parser("lancar", help="lançar eventos variáveis do mês")
    s.add_argument("matricula", type=int)
    s.add_argument("competencia", type=competencia)
    s.add_argument("--he50", dest="horas_extras_50", type=valor, help="horas extras 50%%")
    s.add_argument("--he100", dest="horas_extras_100", type=valor, help="horas extras 100%%")
    s.add_argument("--noturnas", dest="horas_noturnas", type=valor, help="horas trabalhadas entre 22h e 5h")
    s.add_argument("--comissoes", type=valor)
    s.add_argument("--faltas", dest="faltas_dias", type=valor, help="dias de falta")
    s.add_argument("--dias-ferias", dest="dias_ferias", type=valor, help="dias de férias no mês")
    s.add_argument("--feriados", type=valor, help="feriados fora de domingo (DSR)")
    s.add_argument("--outros-proventos", type=valor)
    s.add_argument("--outros-descontos", type=valor)
    s.add_argument("--vt", dest="desconto_vt", type=valor,
                   help="desconto de vale-transporte do mês (substitui o calculado pelo cadastro)")
    s.add_argument("--plano-saude", type=valor)
    s.add_argument("--plano-odonto", type=valor)
    s.add_argument("--vale-alimentacao", type=valor)
    s.add_argument("--seguro-vida", type=valor)
    s.add_argument("--consignado", dest="emprestimo_consignado", type=valor, help="parcela do empréstimo consignado")
    s.add_argument("--sindical", dest="contribuicao_sindical", type=valor, help="contribuição/mensalidade sindical")
    s.add_argument("--farmacia", dest="convenio_farmacia", type=valor, help="convênio farmácia")
    s.set_defaults(func=cmd_lancar)

    s = sub.add_parser("processar", help="calcular a folha mensal")
    s.add_argument("competencia", type=competencia)
    s.set_defaults(func=cmd_processar)

    s = sub.add_parser("adiantamento", help="listar o adiantamento quinzenal")
    s.add_argument("competencia", type=competencia)
    s.set_defaults(func=cmd_adiantamento)

    s = sub.add_parser("ferias", help="calcular recibo de férias")
    s.add_argument("matricula", type=int)
    s.add_argument("competencia", type=competencia, help="mês de início do gozo")
    s.add_argument("--dias", type=int, default=30, help="dias de gozo (padrão 30)")
    s.add_argument("--abono", type=int, default=0, help="dias vendidos (até 10)")
    s.add_argument("--media", type=valor, help="média de variáveis (padrão: calculada)")
    s.set_defaults(func=cmd_ferias)

    s = sub.add_parser("decimo-terceiro", help="calcular 13º de todos os ativos")
    s.add_argument("ano", type=int)
    s.add_argument("--parcela", type=int, choices=(1, 2), required=True)
    s.add_argument("--competencia", type=competencia, help="padrão: novembro (1ª) ou dezembro (2ª)")
    s.add_argument("--media", type=valor, help="média de variáveis para todos (padrão: calculada)")
    s.set_defaults(func=cmd_decimo)

    s = sub.add_parser("rescisao", help="calcular rescisão e desligar")
    s.add_argument("matricula", type=int)
    s.add_argument("--data", type=data, required=True, help="último dia trabalhado (AAAA-MM-DD)")
    s.add_argument("--motivo", choices=list(MOTIVOS), required=True)
    s.add_argument("--aviso", choices=sorted({x for v in MOTIVOS.values() for x in v}),
                   help="padrão: indenizado (dispensa/acordo) ou trabalhado (pedido)")
    s.add_argument("--ferias-vencidas", type=int, default=0, help="períodos completos não gozados")
    s.add_argument("--saldo-fgts", type=valor, default=ZERO, help="saldo da conta do FGTS (multa)")
    s.add_argument("--media", type=valor, help="média de variáveis (padrão: calculada)")
    s.add_argument("--adiantamento-pago", type=valor,
                   help="adiantamento já pago no mês (padrão: o cadastrado, se desligado após o dia 15)")
    s.set_defaults(func=cmd_rescisao)

    s = sub.add_parser("holerite", help="exibir recibo")
    s.add_argument("matricula", type=int)
    s.add_argument("competencia", type=competencia)
    s.add_argument("--folha", choices=banco.FOLHAS, default="mensal")
    s.set_defaults(func=cmd_holerite)

    s = sub.add_parser("resumo", help="resumo de uma folha processada")
    s.add_argument("competencia", type=competencia)
    s.add_argument("--folha", choices=banco.FOLHAS, default="mensal")
    s.add_argument("--csv", help="exportar para arquivo CSV")
    s.set_defaults(func=cmd_resumo)

    s = sub.add_parser("encargos", help="custo da folha, provisões e guias")
    s.add_argument("competencia", type=competencia)
    s.add_argument("--csv", help="exportar custos para CSV")
    s.set_defaults(func=cmd_encargos)
    return p


def main(argv=None):
    try:
        config.carregar_tabelas()  # antes do parser: as opções usam valores das tabelas
    except ValueError as e:
        sys.exit(f"Erro: {e}")
    a = montar_parser().parse_args(argv)
    with banco.conectar(a.banco) as con:
        try:
            a.func(con, a)
        except ValueError as e:
            sys.exit(f"Erro: {e}")
