"""Regras de cálculo da folha mensal. Funções puras: não acessam banco nem tela."""
import calendar
from dataclasses import dataclass, field
from decimal import Decimal as D, ROUND_HALF_UP

from . import tabelas as t

ZERO = D("0")

# Proventos variáveis: entram na média usada em férias, 13º e rescisão
VARIAVEIS = ("Horas extras 50%", "Horas extras 100%", "Adicional noturno",
             "Comissões", "DSR sobre variáveis")


def arred(valor: D) -> D:
    return valor.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def calcular_inss(base: D) -> D:
    """INSS progressivo: cada faixa tributa só a parcela do salário dentro dela."""
    total, anterior = ZERO, ZERO
    for limite, aliquota in t.TABELA_INSS:
        parcela = min(base, limite) - anterior
        if parcela <= 0:
            break
        total += parcela * aliquota
        anterior = limite
    return arred(total)


def _irrf_pela_tabela(base: D) -> D:
    for limite, aliquota, deducao in t.TABELA_IRRF:
        if limite is None or base <= limite:
            return max(ZERO, base * aliquota - deducao)
    return ZERO


def calcular_irrf(rendimentos: D, inss: D, dependentes: int = 0, pensao: D = ZERO,
                  simplificado: bool = True, reducao: bool = True) -> D:
    """IRRF com a regra mais vantajosa (deduções legais x simplificado) e a
    redução de 2026 para quem ganha até R$ 7.350. O 13º (tributação exclusiva)
    não usa o desconto simplificado."""
    deducao = inss + t.DEDUCAO_DEPENDENTE * dependentes + pensao
    if simplificado:
        deducao = max(deducao, t.DESCONTO_SIMPLIFICADO)
    imposto = _irrf_pela_tabela(max(ZERO, rendimentos - deducao))

    if not reducao or rendimentos > t.REDUCAO_IR_LIMITE_FAIXA:
        valor_reducao = ZERO
    elif rendimentos <= t.REDUCAO_IR_LIMITE_ISENCAO:
        valor_reducao = imposto
    else:
        valor_reducao = t.REDUCAO_IR_CONSTANTE - t.REDUCAO_IR_FATOR * rendimentos
    return arred(max(ZERO, imposto - max(ZERO, valor_reducao)))


@dataclass
class Funcionario:
    nome: str
    salario: D
    dependentes: int = 0
    usa_vt: bool = False        # recebe vale-transporte (sem isso não há desconto de VT)
    valor_vt: D = ZERO          # custo mensal do vale-transporte
    pensao: D = ZERO
    insalubridade: int = 0      # grau: 0, 10, 20 ou 40 (% do salário mínimo)
    periculosidade: bool = False
    filhos_sf: int = 0          # filhos até 14 anos (salário-família)
    adiantamento_pct: D = ZERO  # % do salário pago como adiantamento quinzenal
    desconto_vr: D = ZERO       # participação no vale-refeição
    matricula_esocial: str = "" # matrícula enviada no S-2200 (igual à do sistema anterior)
    categoria: int = 101        # Tabela 01 do eSocial (101 = empregado CLT)
    grau_exposicao: int = 1     # agentes nocivos: 1 = não enseja aposentadoria especial
    cpf_pensao: str = ""        # CPF do beneficiário da pensão alimentícia
    id: int | None = None
    cpf: str = ""
    cargo: str = ""
    admissao: str = ""          # AAAA-MM-DD
    ativo: bool = True


@dataclass
class Lancamento:
    """Eventos variáveis do mês."""
    horas_extras_50: D = ZERO
    horas_extras_100: D = ZERO
    horas_noturnas: D = ZERO    # horas de relógio entre 22h e 5h
    comissoes: D = ZERO
    faltas_dias: D = ZERO
    dias_ferias: D = ZERO       # dias de férias gozados dentro da competência
    feriados: D = ZERO          # feriados fora de domingo (para o DSR)
    outros_proventos: D = ZERO
    outros_descontos: D = ZERO
    desconto_vt: D = ZERO       # se informado, substitui o desconto de VT calculado pelo cadastro
    plano_saude: D = ZERO
    plano_odonto: D = ZERO
    vale_alimentacao: D = ZERO
    seguro_vida: D = ZERO
    emprestimo_consignado: D = ZERO
    contribuicao_sindical: D = ZERO
    convenio_farmacia: D = ZERO


# Descontos lançados no mês (R$): campo do Lancamento -> descrição no recibo
DESCONTOS_LANCAMENTO = {
    "plano_saude": "Plano de saúde",
    "plano_odonto": "Plano odontológico",
    "vale_alimentacao": "Vale-alimentação",
    "seguro_vida": "Seguro de vida",
    "emprestimo_consignado": "Empréstimo consignado",
    "contribuicao_sindical": "Contribuição sindical",
    "convenio_farmacia": "Convênio farmácia",
}


@dataclass
class Holerite:
    proventos: dict[str, D] = field(default_factory=dict)
    descontos: dict[str, D] = field(default_factory=dict)
    bases: dict[str, D] = field(default_factory=dict)  # bases de cálculo e informativos

    @property
    def base_inss(self) -> D:
        return self.bases.get("Base INSS", ZERO)

    @property
    def base_fgts(self) -> D:
        return self.bases.get("Base FGTS", ZERO)

    @property
    def fgts(self) -> D:
        return self.bases.get("FGTS", ZERO)

    @property
    def total_proventos(self) -> D:
        return sum(self.proventos.values(), ZERO)

    @property
    def total_descontos(self) -> D:
        return sum(self.descontos.values(), ZERO)

    @property
    def liquido(self) -> D:
        return self.total_proventos - self.total_descontos


def adicional_fixo(func: Funcionario) -> tuple[str, D] | None:
    """Insalubridade ou periculosidade. Não se acumulam (CLT art. 193 §2º):
    paga-se o mais vantajoso."""
    insal = t.SALARIO_MINIMO * func.insalubridade / 100
    peric = func.salario * t.ALIQUOTA_PERICULOSIDADE if func.periculosidade else ZERO
    if not insal and not peric:
        return None
    if peric >= insal:
        return "Adicional de periculosidade", arred(peric)
    return f"Adicional de insalubridade {func.insalubridade}%", arred(insal)


def remuneracao_fixa(func: Funcionario) -> D:
    adicional = adicional_fixo(func)
    return func.salario + (adicional[1] if adicional else ZERO)


def valor_adiantamento(func: Funcionario) -> D:
    return arred(func.salario * func.adiantamento_pct / 100)


def dias_uteis_e_descanso(competencia: str, feriados: D = ZERO) -> tuple[int, int]:
    ano, mes = map(int, competencia.split("-"))
    total = calendar.monthrange(ano, mes)[1]
    domingos = sum(1 for d in range(1, total + 1) if calendar.weekday(ano, mes, d) == 6)
    descanso = domingos + int(feriados)
    return total - descanso, descanso


def calcular_folha(func: Funcionario, lanc: Lancamento | None = None, competencia: str | None = None,
                   base_inss_ferias: D = ZERO, inss_ferias: D = ZERO) -> Holerite:
    """Folha mensal. Sem `competencia` o DSR não é calculado. Se houve férias no
    mês, informe a base e o INSS do recibo de férias para consolidar o INSS."""
    lanc = lanc or Lancamento()
    h = Holerite()
    dias_trab = t.DIAS_MES_COMERCIAL - lanc.dias_ferias
    proporcao = dias_trab / t.DIAS_MES_COMERCIAL
    valor_hora = remuneracao_fixa(func) / t.JORNADA_MENSAL_HORAS

    rotulo = f"Salário ({int(dias_trab)} dias)" if lanc.dias_ferias else "Salário base"
    h.proventos[rotulo] = arred(func.salario * proporcao)
    if adicional := adicional_fixo(func):
        h.proventos[adicional[0]] = arred(adicional[1] * proporcao)
    if lanc.horas_extras_50:
        h.proventos["Horas extras 50%"] = arred(valor_hora * D("1.5") * lanc.horas_extras_50)
    if lanc.horas_extras_100:
        h.proventos["Horas extras 100%"] = arred(valor_hora * 2 * lanc.horas_extras_100)
    if lanc.horas_noturnas:
        h.proventos["Adicional noturno"] = arred(
            valor_hora * t.ADICIONAL_NOTURNO * lanc.horas_noturnas * t.FATOR_HORA_NOTURNA)
    if lanc.comissoes:
        h.proventos["Comissões"] = arred(lanc.comissoes)

    variaveis = sum((h.proventos.get(k, ZERO) for k in VARIAVEIS), ZERO)
    if variaveis and competencia:
        uteis, descanso = dias_uteis_e_descanso(competencia, lanc.feriados)
        h.proventos["DSR sobre variáveis"] = arred(variaveis / uteis * descanso)

    if lanc.outros_proventos:
        h.proventos["Outros proventos"] = arred(lanc.outros_proventos)
    if lanc.faltas_dias:
        h.descontos["Faltas"] = arred(remuneracao_fixa(func) / t.DIAS_MES_COMERCIAL * lanc.faltas_dias)

    # Base tributável = proventos menos faltas (salário-família entra depois: não é tributável)
    base = h.total_proventos - h.descontos.get("Faltas", ZERO)
    h.bases["Base INSS"] = h.bases["Base FGTS"] = base

    inss = max(ZERO, calcular_inss(base + base_inss_ferias) - inss_ferias)
    h.descontos["INSS"] = inss
    if irrf := calcular_irrf(base, inss, func.dependentes, func.pensao):
        h.descontos["IRRF"] = irrf
    if func.pensao:
        h.descontos["Pensão alimentícia"] = arred(func.pensao)
    if func.usa_vt and lanc.desconto_vt:
        h.descontos["Vale-transporte"] = arred(lanc.desconto_vt)
    elif func.usa_vt and func.valor_vt:
        h.descontos["Vale-transporte"] = arred(min(func.salario * t.ALIQUOTA_VT, func.valor_vt))
    if func.desconto_vr:
        h.descontos["Vale-refeição"] = arred(func.desconto_vr)
    if func.adiantamento_pct:
        h.descontos["Adiantamento salarial"] = valor_adiantamento(func)
    for campo, rotulo in DESCONTOS_LANCAMENTO.items():
        if valor := getattr(lanc, campo):
            h.descontos[rotulo] = arred(valor)
    if lanc.outros_descontos:
        h.descontos["Outros descontos"] = arred(lanc.outros_descontos)

    if func.filhos_sf and base + base_inss_ferias <= t.SALARIO_FAMILIA_LIMITE:
        h.proventos["Salário-família"] = arred(t.SALARIO_FAMILIA_COTA * func.filhos_sf)

    h.bases["FGTS"] = arred(base * t.ALIQUOTA_FGTS)
    return h
