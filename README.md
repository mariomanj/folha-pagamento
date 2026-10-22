# Folha de Pagamento

Sistema de folha de pagamento para empresas brasileiras (regime CLT), em Python
puro — sem dependências externas. Funciona totalmente offline; dados armazenados em SQLite (`folha.db`).

## Executável para Windows (sem internet)

O arquivo `dist\FolhaPagamento.exe` é o programa completo com interface gráfica. Para instalar
em outro computador, **copie só esse arquivo**: não precisa de Python, de internet nem de
instalação. Dê dois cliques para abrir.

- Os dados ficam em `Documentos\FolhaPagamento` (`folha.db` e `tabelas.json`).
- Para levar os dados a outro computador, copie essa pasta inteira para o mesmo lugar no outro
  computador. Faça backups pela aba **Configurações → Fazer backup**.
- Tabelas legais (INSS, IRRF, salário mínimo...) ficam em `tabelas.json`: na virada do ano, altere
  esse arquivo (aba Configurações → Abrir arquivo de tabelas) e clique em **Recarregar**. Não é
  preciso gerar um novo executável.
- Na primeira execução o Windows SmartScreen pode avisar que o programa não é reconhecido
  (o executável não tem assinatura digital): clique em **Mais informações → Executar assim mesmo**.

### Uso da interface

1. **Configurações:** razão social, CNPJ e regime tributário (Simples Nacional ou não).
2. **Funcionários:** cadastre, edite, calcule férias e rescisão.
3. **Lançamentos:** escolha a competência, selecione o funcionário e lance horas extras, faltas etc.
4. **Folha:** processe a folha mensal ou o 13º, veja/imprima os recibos, exporte para Excel.
5. **Encargos e guias:** custo por funcionário e valores da DCTFWeb e do FGTS Digital.
6. **eSocial:** geração e envio dos eventos mensais (ver seção eSocial).

### Gerar o executável novamente (após alterar o código)

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

O script roda os testes e, se passarem, gera `dist\FolhaPagamento.exe`. Na primeira vez ele
baixa o PyInstaller (precisa de internet só nessa máquina de desenvolvimento).

## Linha de comando (opcional, requer Python 3.10+)

Interface gráfica a partir do código-fonte: `python -m folha.gui`.

Valores aceitam `3500`, `3500.50` ou `3.500,50`. Use `python -m folha <comando> --help`
para ver todas as opções.

### Cadastro

```powershell
python -m folha admitir --nome "Maria Souza" --salario 3500 --admissao 2023-02-01 `
    --dependentes 1 --vt 220 --vr 50 --adiantamento 40
python -m folha admitir --nome "Carla Dias" --salario 1650 --admissao 2026-03-17 `
    --insalubridade 20 --filhos-sf 1
python -m folha alterar 1 --salario 3800 --periculosidade sim
python -m folha listar
```

### Folha mensal

```powershell
# Eventos do mês (só os campos informados são alterados)
python -m folha lancar 1 2026-10 --he50 8 --he100 2 --noturnas 20 --comissoes 500 --faltas 1 --feriados 1
python -m folha adiantamento 2026-10          # valores da quinzena
python -m folha processar 2026-10             # calcula a folha de todos os ativos
python -m folha holerite 1 2026-10
python -m folha resumo 2026-10 --csv resumo-2026-10.csv
```

### Férias, 13º e rescisão

```powershell
python -m folha ferias 3 2026-10 --dias 20 --abono 10     # gere ANTES de processar o mês
python -m folha decimo-terceiro 2026 --parcela 1          # competência 2026-11
python -m folha decimo-terceiro 2026 --parcela 2          # competência 2026-12
python -m folha rescisao 1 --data 2026-11-20 --motivo sem_justa_causa --saldo-fgts 12000
python -m folha holerite 1 2026-11 --folha rescisao
```

Motivos de rescisão: `sem_justa_causa`, `acordo`, `pedido_demissao`, `justa_causa`.
Aviso prévio: `indenizado`, `trabalhado`, `nao_cumprido` (desconta do empregado), `dispensado`.

A média de horas extras, adicional noturno, comissões e DSR é calculada a partir das
folhas mensais já gravadas (12 meses anteriores para férias e rescisão; o ano corrente
para o 13º). Use `--media VALOR` para informá-la manualmente.

### Encargos e guias

```powershell
python -m folha encargos 2026-10 --csv custos-2026-10.csv
```

Mostra o custo de cada funcionário (encargos patronais, FGTS, provisões de férias e 13º)
e os totais a recolher na competência: DCTFWeb (INSS segurados + empresa − salário-família,
IRRF) e FGTS Digital (mensal + multas rescisórias).

## eSocial (leiaute S-1.3)

O programa gera, assina com o certificado A1 e transmite os eventos do ciclo mensal:

| Evento | Conteúdo |
|---|---|
| S-1010 | Tabela de rubricas deste programa (enviada uma vez; reenviada só se uma rubrica mudar) |
| S-1200 | Remuneração: folha mensal e recibo de férias de cada funcionário |
| S-1210 | Pagamentos feitos no mês (conforme a **data de pagamento** de cada folha) |
| S-1299 | Fechamento do mês |

Internet só é necessária para **enviar** e **consultar retornos**. Gerar, validar e conferir os
XMLs funciona offline: os esquemas oficiais (XSD) ficam embutidos no programa.

### Configuração (uma vez)

1. **Configurações:** CNPJ da empresa.
2. **eSocial → Configurar:**
   - *Código da lotação tributária*: o mesmo enviado no S-1020 pelo sistema anterior.
   - *Primeira competência neste programa*: mês em que este programa assume o eSocial.
   - *Ambiente*: comece em **produção restrita** (testes).
3. **eSocial → Certificado A1:** escolha o arquivo `.pfx`. A senha é pedida no primeiro envio e
   fica só na memória enquanto o programa estiver aberto.
4. **Funcionários → Editar:** CPF e **matrícula no eSocial** de cada um. A matrícula deve ser
   **idêntica** à enviada pelo sistema anterior no S-2200 (consulte no portal do eSocial ou no
   sistema anterior). Para quem tem pensão alimentícia, informe o CPF do beneficiário.
5. **Rubricas:** revise com o contador o arquivo de rubricas (Configurações → Rubricas do eSocial):
   natureza (Tabela 03) e incidências de INSS, IRRF e FGTS de cada verba.

### Rotina mensal

1. Processe a folha (aba Folha) e defina a **data de pagamento** (botão *Data de pagamento...*).
2. Aba eSocial: **1. Gerar eventos** → **2. Enviar próxima etapa** → aguarde alguns minutos →
   **3. Consultar retornos**. Repita 2 e 3 até concluir as etapas S-1010 → S-1200 → S-1210 → S-1299.
3. Eventos rejeitados ficam em vermelho; dê duplo clique para ver a mensagem do eSocial, corrija e
   gere de novo. Alterações em folhas já aceitas viram **retificação** automaticamente.

### Transição do sistema anterior

- Só um sistema pode enviar o S-1210 de cada funcionário em cada mês. No primeiro mês, o pagamento
  da última folha do sistema anterior deve ir no S-1210 deste programa: importe esses pagamentos em
  **eSocial → Pagamentos do sistema anterior** (CSV com `cpf;data;competencia;ide_dm_dev;valor`).
- **Ainda não gerados por este programa** (continue usando o sistema anterior ou o eSocial Web
  Geral): admissão (S-2200), alterações contratuais (S-2206), afastamentos (S-2230),
  desligamento (S-2299) e 13º salário (S-1200 anual).

### Antivírus

Antivírus que inspecionam conexões HTTPS (ex.: **Norton Web/Mail Shield**, Kaspersky, Avast) podem
impedir a autenticação com o certificado. Se o envio falhar com erro de conexão segura, crie uma
exceção para `*.esocial.gov.br`.

### Diagnóstico

`FolhaPagamento.exe --autoteste` grava `autoteste.txt` na pasta de dados com a validação de um
evento de cada tipo contra os esquemas embutidos.

## Testes

```powershell
python -m unittest -v
```

## Estrutura

| Arquivo | Responsabilidade |
|---|---|
| `folha/tabelas.py` | Tabelas legais e **parâmetros da empresa** (regime, RAT, FAP, terceiros) — atualizar todo ano |
| `folha/calculo.py` | Folha mensal e funções base (INSS, IRRF, adicionais) |
| `folha/ferias.py` | Recibo de férias |
| `folha/decimo_terceiro.py` | 1ª e 2ª parcelas do 13º |
| `folha/rescisao.py` | Verbas rescisórias |
| `folha/encargos.py` | Encargos patronais, provisões e guias |
| `folha/datas.py` | Avos de 13º e férias, tempo de serviço |
| `folha/banco.py` | Persistência SQLite (com migração automática de bancos antigos) |
| `folha/relatorios.py` | Recibos em texto e exportação CSV |
| `folha/servicos.py` | Operações usadas pela interface e pela linha de comando |
| `folha/gui.py` | Interface gráfica (Tkinter) |
| `folha/config.py` | Pasta de dados e tabelas editáveis (`tabelas.json`) |
| `folha/cli.py` | Comandos de linha de comando |
| `folha/esocial/` | eSocial: rubricas, eventos, assinatura, validação (XSD em `recursos/`), webservices |
| `app.py`, `build.ps1` | Geração do executável |
| `tests/` | Testes automatizados das regras |

## Regras implementadas

**Folha mensal**
- Salário base, horas extras 50% e 100% (divisor 220h), adicional noturno de 20% com hora
  reduzida de 52min30s, comissões, DSR sobre variáveis (domingos + feriados informados)
- Insalubridade (10/20/40% do salário mínimo) ou periculosidade (30% do salário): paga-se o
  maior, e o adicional integra a base das horas extras
- Salário-família (fora da base de INSS/IRRF), adiantamento quinzenal, vale-transporte
  (até 6%), vale-refeição, pensão alimentícia, faltas
- INSS progressivo com teto; no mês de férias, o INSS é consolidado com o recibo de férias
- IRRF 2026: o mais vantajoso entre deduções legais e desconto simplificado, com a redução
  da Lei 15.270/2025 (isenção até R$ 5.000 e redução parcial até R$ 7.350)

**Férias:** gozo de 5 a 30 dias, 1/3 constitucional, abono pecuniário (até 10 dias, isento),
média de variáveis, INSS/IRRF/FGTS.

**13º salário:** avos por mês com 15+ dias trabalhados; 1ª parcela sem descontos; 2ª parcela
com INSS e IRRF exclusivo na fonte, descontando a 1ª.

**Rescisão:** saldo de salário, aviso prévio proporcional (Lei 12.506: 30 + 3 dias por ano,
até 90) com projeção para 13º e férias, acordo (art. 484-A: metade do aviso e multa de 20%),
13º proporcional, férias vencidas e proporcionais + 1/3, multa de 40% do FGTS, desconto de
aviso não cumprido. Aviso indenizado e férias indenizadas são isentos de INSS e IRRF.

**Encargos:** INSS patronal 20%, RAT × FAP, terceiros, FGTS 8%, provisões de 13º e férias com
encargos. Empresas do Simples Nacional: altere `EMPRESA_SIMPLES_NACIONAL` em `tabelas.py`.

Valores com `Decimal` e arredondamento ROUND_HALF_UP (sem erros de ponto flutuante).

> ⚠️ Confira os valores em `folha/tabelas.py` com as publicações oficiais da Receita
> Federal e do Ministério da Previdência antes de usar com dados reais. Pontos marcados
> com "confirmar" (salário-família, redução do IR no 13º) merecem atenção especial.

### Simplificações conhecidas

- Férias que atravessam o mês: o recibo inteiro fica na competência de início; ajuste os dias
  de cada mês com `lancar --dias-ferias`.
- Faltas não reduzem o DSR nem os dias de férias (CLT art. 130).
- A média de variáveis usa valores, não quantidade de horas × salário atual.
- Salário-família e vale-transporte não são proporcionais aos dias trabalhados.

## Roteiro

1. ~~Mais eventos (DSR, adicional noturno, insalubridade/periculosidade, comissões,
   salário-família, vale-refeição, adiantamento)~~ ✅
2. ~~Férias e 13º~~ ✅
3. ~~Rescisão~~ ✅
4. ~~Encargos patronais e provisões~~ ✅
5. ~~Interface desktop e executável offline~~ ✅
6. ~~eSocial — ciclo mensal (S-1010, S-1200, S-1210, S-1299) com certificado A1~~ ✅
   - Próximos: 13º (S-1200 anual), S-2299 desligamento, S-2200 admissão, S-2206 alteração, S-2230
7. **Relatórios:** holerite e TRCT em PDF, informe de rendimentos anual
8. **Segurança/LGPD:** controle de acesso, log de auditoria, backup e criptografia dos dados pessoais
