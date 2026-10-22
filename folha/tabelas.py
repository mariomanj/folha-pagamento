"""Tabelas legais vigentes (competência 2026) e parâmetros da empresa.

ATENÇÃO: valores mudam todo ano. Confira as portarias da Receita Federal e do
Ministério da Previdência antes de usar em produção. Estes são os valores
padrão: o arquivo tabelas.json da pasta de dados (ver config.py) os substitui,
o que permite atualizar o executável sem recompilar.
"""
from decimal import Decimal as D

SALARIO_MINIMO = D("1621.00")

# INSS empregado — progressivo: (limite superior da faixa, alíquota)
TABELA_INSS = [
    (D("1621.00"), D("0.075")),
    (D("2902.84"), D("0.09")),
    (D("4354.27"), D("0.12")),
    (D("8475.55"), D("0.14")),  # teto do salário de contribuição
]

# IRRF mensal: (limite superior, alíquota, parcela a deduzir); None = sem limite
TABELA_IRRF = [
    (D("2428.80"), D("0"), D("0")),
    (D("2826.65"), D("0.075"), D("182.16")),
    (D("3751.05"), D("0.15"), D("394.16")),
    (D("4664.68"), D("0.225"), D("675.49")),
    (None, D("0.275"), D("908.73")),
]
DEDUCAO_DEPENDENTE = D("189.59")
DESCONTO_SIMPLIFICADO = D("607.20")

# Redução do IRRF (Lei 15.270/2025), aplicada sobre os rendimentos tributáveis
REDUCAO_IR_LIMITE_ISENCAO = D("5000.00")   # até aqui o imposto é zerado
REDUCAO_IR_LIMITE_FAIXA = D("7350.00")     # acima daqui não há redução
REDUCAO_IR_CONSTANTE = D("978.62")
REDUCAO_IR_FATOR = D("0.133145")
REDUCAO_IR_APLICA_13 = True                # confirmar regra da Receita para o 13º

# Salário-família (por filho até 14 anos) — confirmar portaria do ano
SALARIO_FAMILIA_LIMITE = D("1980.38")
SALARIO_FAMILIA_COTA = D("67.54")

ALIQUOTA_FGTS = D("0.08")
ALIQUOTA_VT = D("0.06")          # desconto máximo do vale-transporte
ALIQUOTA_PERICULOSIDADE = D("0.30")        # sobre o salário base
GRAUS_INSALUBRIDADE = (0, 10, 20, 40)      # % sobre o salário mínimo
ADICIONAL_NOTURNO = D("0.20")
FATOR_HORA_NOTURNA = D("60") / D("52.5")   # hora noturna reduzida (52min30s)
JORNADA_MENSAL_HORAS = D("220")
DIAS_MES_COMERCIAL = D("30")

# Aviso prévio (Lei 12.506/2011)
AVISO_DIAS_BASE = 30
AVISO_DIAS_POR_ANO = 3
AVISO_DIAS_MAXIMO = 90

MULTA_FGTS = {"sem_justa_causa": D("0.40"), "acordo": D("0.20")}

# --- Parâmetros da empresa (ajuste conforme o CNPJ) ---------------------------
EMPRESA_NOME = ""
EMPRESA_CNPJ = ""
EMPRESA_SIMPLES_NACIONAL = False   # True = sem INSS patronal/RAT/terceiros (Anexos I a III e V)
ALIQUOTA_INSS_PATRONAL = D("0.20")
ALIQUOTA_RAT = D("0.02")           # 1%, 2% ou 3% conforme o CNAE
FAP = D("1.0000")                  # entre 0,5 e 2,0
ALIQUOTA_TERCEIROS = D("0.058")    # Sistema S, salário-educação, Incra (varia pelo FPAS)

# --- eSocial -------------------------------------------------------------------
ESOCIAL_AMBIENTE = 2                # 2 = produção restrita (testes); 1 = produção
ESOCIAL_CNPJ_ESTABELECIMENTO = ""   # vazio = CNPJ da empresa
ESOCIAL_COD_LOTACAO = ""            # código da lotação enviado no S-1020 (pelo sistema anterior)
ESOCIAL_TAB_RUBRICAS = "FOLHA"      # identificador da tabela de rubricas deste programa
ESOCIAL_INICIO_RUBRICAS = ""        # AAAA-MM: primeira competência enviada por este programa
ESOCIAL_CERTIFICADO = ""            # caminho do certificado A1 (.pfx)
