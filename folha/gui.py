"""Interface gráfica (Tkinter). Funciona sem internet.  python -m folha.gui"""
import functools
import os
import re
import sys
import tempfile
import tkinter as tk
import traceback
from datetime import date, datetime
from decimal import Decimal as D, InvalidOperation
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from lxml import etree

from . import banco, config, servicos, tabelas
from .calculo import ZERO, Funcionario
from .esocial import assinatura as es_assinatura, rubricas as es_rubricas, servico as es_servico
from .esocial.webservice import ErroComunicacao
from .relatorios import exportar_custos_csv, exportar_resumo_csv, holerite_texto, numero
from .rescisao import MOTIVOS

VERSAO = "1.1"

NOMES_FOLHA = {"mensal": "Mensal", "ferias": "Férias", "13-1": "13º — 1ª parcela",
               "13-2": "13º — 2ª parcela", "rescisao": "Rescisão"}
NOMES_MOTIVO = {"sem_justa_causa": "Dispensa sem justa causa", "acordo": "Acordo (art. 484-A)",
                "pedido_demissao": "Pedido de demissão", "justa_causa": "Justa causa"}
NOMES_AVISO = {"indenizado": "Indenizado", "trabalhado": "Trabalhado", "nao_cumprido":
               "Não cumprido (descontar)", "dispensado": "Dispensado pela empresa", "nenhum": "Não se aplica"}
GRAUS = {0: "Não", 10: "Grau mínimo (10%)", 20: "Grau médio (20%)", 40: "Grau máximo (40%)"}
GRAUS_EXPOSICAO = {1: "Não enseja aposentadoria especial", 2: "Aposentadoria especial 15 anos",
                   3: "Aposentadoria especial 20 anos", 4: "Aposentadoria especial 25 anos"}
AMBIENTES = {2: "Produção restrita (testes)", 1: "Produção (oficial)"}
SITUACOES = {"gerado": "A enviar", "enviado": "Aguardando retorno", "aceito": "Aceito", "rejeitado": "Rejeitado"}


# --- conversão de texto -------------------------------------------------------------

def ler_valor(texto: str, rotulo: str) -> D:
    texto = texto.strip().replace("R$", "").strip()
    if not texto:
        return ZERO
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return D(texto)
    except InvalidOperation:
        raise ValueError(f"{rotulo}: valor inválido ({texto})")


def ler_data(texto: str, rotulo: str) -> str:
    """'15/10/2026' ou '2026-10-15' -> '2026-10-15'; vazio -> ''."""
    texto = texto.strip()
    if not texto:
        return ""
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"{rotulo}: use DD/MM/AAAA")


def ler_competencia(texto: str) -> str:
    """'10/2026' ou '2026-10' -> '2026-10'."""
    texto = texto.strip()
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", texto):
        texto = f"{m[2]}-{int(m[1]):02d}"
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", texto):
        raise ValueError("Competência: use MM/AAAA, ex.: 10/2026")
    return texto


def mostrar_competencia(comp: str) -> str:
    return f"{comp[5:]}/{comp[:4]}"


def mostrar_data(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""


def mostrar_decimal(v: D) -> str:
    """Sem arredondar (ex.: FAP 0,9876)."""
    return format(v.normalize(), "f").replace(".", ",") if v else ""


def tratar_erros(fn):
    """Mostra erros numa caixa de mensagem em vez de derrubar o programa."""
    @functools.wraps(fn)
    def envolvida(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            messagebox.showerror("Verifique os dados", str(e))
        except Exception:
            messagebox.showerror("Erro inesperado", traceback.format_exc(limit=3))
    return envolvida


# --- componentes ---------------------------------------------------------------------

class Formulario(ttk.Frame):
    """Grade de campos. Cada campo: (nome, rótulo, tipo[, opções]). Tipos: texto,
    valor, valor_opcional, decimal, percentual, inteiro, data, competencia, bool, escolha."""

    def __init__(self, master, campos, colunas=1, largura=22):
        super().__init__(master)
        self.campos = {c[0]: c for c in campos}
        self.vars = {}
        for i, (nome, rotulo, tipo, *extra) in enumerate(campos):
            linha, col = divmod(i, colunas)
            if tipo == "bool":
                var = tk.BooleanVar()
                ttk.Checkbutton(self, text=rotulo, variable=var).grid(
                    row=linha, column=col * 2 + 1, sticky="w", padx=4, pady=3)
            else:
                var = tk.StringVar()
                ttk.Label(self, text=rotulo + ":").grid(row=linha, column=col * 2, sticky="e", padx=(12, 4), pady=3)
                if tipo == "escolha":
                    w = ttk.Combobox(self, textvariable=var, values=list(extra[0].values()),
                                     state="readonly", width=largura)
                else:
                    w = ttk.Entry(self, textvariable=var, width=largura + 2)
                w.grid(row=linha, column=col * 2 + 1, sticky="w", padx=4, pady=3)
            self.vars[nome] = var

    def obter(self) -> dict:
        dados = {}
        for nome, (_, rotulo, tipo, *extra) in self.campos.items():
            bruto = self.vars[nome].get()
            if tipo == "bool":
                dados[nome] = bool(bruto)
            elif tipo == "escolha":
                dados[nome] = next((k for k, v in extra[0].items() if v == bruto), None)
            elif tipo in ("valor", "decimal"):
                dados[nome] = ler_valor(bruto, rotulo)
            elif tipo == "valor_opcional":
                dados[nome] = ler_valor(bruto, rotulo) if bruto.strip() else None
            elif tipo == "percentual":
                dados[nome] = ler_valor(bruto, rotulo) / 100
            elif tipo == "inteiro":
                try:
                    dados[nome] = int(bruto.strip() or 0)
                except ValueError:
                    raise ValueError(f"{rotulo}: informe um número inteiro")
            elif tipo == "data":
                dados[nome] = ler_data(bruto, rotulo)
            elif tipo == "competencia":
                dados[nome] = ler_competencia(bruto) if bruto.strip() else ""
            else:
                dados[nome] = bruto.strip()
        return dados

    def definir(self, valores: dict):
        for nome, v in valores.items():
            if nome not in self.campos:
                continue
            tipo, extra = self.campos[nome][2], self.campos[nome][3:]
            if tipo == "bool":
                texto = bool(v)
            elif tipo == "escolha":
                texto = extra[0].get(v, "")
            elif tipo == "valor":
                texto = numero(v) if v else ""
            elif tipo == "decimal":
                texto = mostrar_decimal(v)
            elif tipo == "percentual":
                texto = mostrar_decimal(v * 100)
            elif tipo == "inteiro":
                texto = str(v) if v else ""
            elif tipo == "data":
                texto = mostrar_data(v)
            elif tipo == "competencia":
                texto = mostrar_competencia(v) if v else ""
            else:
                texto = "" if v is None else str(v)
            self.vars[nome].set(texto)


class Tabela(ttk.Frame):
    """Treeview com barra de rolagem e linha de total em negrito."""

    def __init__(self, master, colunas: list[tuple[str, int, str]], altura=15):
        super().__init__(master)
        self.arvore = ttk.Treeview(self, columns=[c[0] for c in colunas], show="headings",
                                   height=altura, selectmode="browse")
        for nome, largura, alinhamento in colunas:
            self.arvore.heading(nome, text=nome)
            self.arvore.column(nome, width=largura, anchor=alinhamento, stretch=alinhamento == "w")
        self.arvore.tag_configure("total", font=("Segoe UI", 9, "bold"))
        rolagem = ttk.Scrollbar(self, orient="vertical", command=self.arvore.yview)
        self.arvore.configure(yscrollcommand=rolagem.set)
        self.arvore.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")

    def preencher(self, linhas: list[tuple[str, list]], total: list | None = None):
        """linhas: (id, valores). O id identifica a linha na seleção."""
        self.arvore.delete(*self.arvore.get_children())
        for iid, valores in linhas:
            self.arvore.insert("", "end", iid=iid, values=valores)
        if total:
            self.arvore.insert("", "end", iid="__total__", values=total, tags=("total",))

    def selecionado(self) -> str | None:
        sel = self.arvore.selection()
        return sel[0] if sel and sel[0] != "__total__" else None


class Dialogo(tk.Toplevel):
    """Janela modal com formulário e botões OK/Cancelar. `self.resultado`
    recebe o dict do formulário se o usuário confirmar e `validar` não falhar."""

    def __init__(self, master, titulo, campos, valores=None, colunas=1, texto_ok="Salvar", validar=None):
        super().__init__(master)
        self.title(titulo)
        self.resizable(False, False)
        self.transient(master)
        self.resultado = None
        self.validar = validar
        self.form = Formulario(self, campos, colunas)
        self.form.pack(padx=12, pady=12)
        if valores:
            self.form.definir(valores)
        botoes = ttk.Frame(self)
        botoes.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(botoes, text=texto_ok, command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.wait_window()

    @tratar_erros
    def _ok(self):
        dados = self.form.obter()
        if self.validar:
            self.validar(dados)
        self.resultado = dados
        self.destroy()


def imprimir_texto(texto: str):
    caminho = Path(tempfile.gettempdir()) / f"folha_{datetime.now():%Y%m%d_%H%M%S}.txt"
    caminho.write_text(texto, encoding="utf-8")
    os.startfile(caminho, "print")


class JanelaRecibo(tk.Toplevel):
    def __init__(self, master, titulo: str, texto: str):
        super().__init__(master)
        self.title(titulo)
        self.texto = texto
        caixa = tk.Text(self, font=("Consolas", 10), width=74, height=34, wrap="none")
        caixa.insert("1.0", texto)
        caixa.configure(state="disabled")
        caixa.pack(fill="both", expand=True, padx=8, pady=8)
        botoes = ttk.Frame(self)
        botoes.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(botoes, text="Fechar", command=self.destroy).pack(side="right")
        ttk.Button(botoes, text="Salvar como...", command=self.salvar).pack(side="right", padx=6)
        ttk.Button(botoes, text="Imprimir", command=lambda: imprimir_texto(self.texto)).pack(side="right")

    @tratar_erros
    def salvar(self):
        if caminho := filedialog.asksaveasfilename(parent=self, defaultextension=".txt",
                                                   filetypes=[("Texto", "*.txt")]):
            Path(caminho).write_text(self.texto, encoding="utf-8")


def barra_competencia(master, var: tk.StringVar, rotulo="Competência (MM/AAAA):") -> ttk.Frame:
    barra = ttk.Frame(master)
    ttk.Label(barra, text=rotulo).pack(side="left")
    ttk.Entry(barra, textvariable=var, width=10).pack(side="left", padx=(4, 12))
    return barra


# --- abas ----------------------------------------------------------------------------

CAMPOS_FUNCIONARIO = [
    ("nome", "Nome *", "texto"),
    ("cpf", "CPF", "texto"),
    ("cargo", "Cargo", "texto"),
    ("admissao", "Admissão (DD/MM/AAAA)", "data"),
    ("salario", "Salário base *", "valor"),
    ("dependentes", "Dependentes (IR)", "inteiro"),
    ("usa_vt", "Usa vale-transporte", "bool"),
    ("valor_vt", "Vale-transporte (custo/mês)", "valor"),
    ("desconto_vr", "Desconto vale-refeição", "valor"),
    ("pensao", "Pensão alimentícia", "valor"),
    ("insalubridade", "Insalubridade", "escolha", GRAUS),
    ("filhos_sf", "Filhos até 14 (sal.-família)", "inteiro"),
    ("adiantamento_pct", "Adiantamento quinzenal (%)", "valor"),
    ("matricula_esocial", "Matrícula no eSocial", "texto"),
    ("categoria", "Categoria eSocial (101 = CLT)", "inteiro"),
    ("grau_exposicao", "Agentes nocivos (eSocial)", "escolha", GRAUS_EXPOSICAO),
    ("cpf_pensao", "CPF do beneficiário da pensão", "texto"),
    ("periculosidade", "Periculosidade (30%)", "bool"),
]


def validar_funcionario(dados):
    if not dados["nome"]:
        raise ValueError("Informe o nome.")
    if dados["salario"] <= 0:
        raise ValueError("Informe o salário base.")
    if not dados["categoria"]:
        dados["categoria"] = 101


class AbaFuncionarios(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        barra = ttk.Frame(self)
        barra.pack(fill="x", pady=(0, 8))
        ttk.Button(barra, text="Novo funcionário", command=self.novo).pack(side="left")
        ttk.Button(barra, text="Editar", command=self.editar).pack(side="left", padx=6)
        ttk.Button(barra, text="Férias...", command=self.ferias).pack(side="left")
        ttk.Button(barra, text="Rescisão...", command=self.rescisao).pack(side="left", padx=6)
        self.todos = tk.BooleanVar()
        ttk.Checkbutton(barra, text="Mostrar desligados", variable=self.todos,
                        command=self.atualizar).pack(side="right")
        self.tabela = Tabela(self, [("Matrícula", 70, "center"), ("Nome", 260, "w"), ("Cargo", 160, "w"),
                                    ("Admissão", 90, "center"), ("Salário", 110, "e"),
                                    ("Dependentes", 90, "center"), ("Situação", 90, "center")], altura=20)
        self.tabela.pack(fill="both", expand=True)
        self.tabela.arvore.bind("<Double-1>", lambda e: self.editar())
        self.atualizar()

    def atualizar(self):
        funcs = banco.listar_funcionarios(self.app.con, somente_ativos=not self.todos.get())
        self.tabela.preencher([(str(f.id), [f.id, f.nome, f.cargo, mostrar_data(f.admissao), numero(f.salario),
                                            f.dependentes, "Ativo" if f.ativo else "Desligado"]) for f in funcs])

    def _selecionado(self) -> Funcionario | None:
        if not (iid := self.tabela.selecionado()):
            messagebox.showinfo("Funcionários", "Selecione um funcionário na lista.")
            return None
        return banco.obter_funcionario(self.app.con, int(iid))

    @tratar_erros
    def novo(self):
        d = Dialogo(self, "Novo funcionário", CAMPOS_FUNCIONARIO,
                    {"insalubridade": 0, "categoria": 101, "grau_exposicao": 1}, colunas=2,
                    validar=validar_funcionario)
        if d.resultado:
            f = Funcionario(**d.resultado)
            matricula = banco.inserir_funcionario(self.app.con, f)
            self.atualizar()
            messagebox.showinfo("Funcionários", f"{f.nome} cadastrado com a matrícula {matricula}.")

    @tratar_erros
    def editar(self):
        if not (f := self._selecionado()):
            return
        d = Dialogo(self, f"Editar — {f.nome}", CAMPOS_FUNCIONARIO, vars(f), colunas=2,
                    validar=validar_funcionario)
        if d.resultado:
            for campo, v in d.resultado.items():
                setattr(f, campo, v)
            banco.atualizar_funcionario(self.app.con, f)
            self.atualizar()

    @tratar_erros
    def ferias(self):
        if not (f := self._selecionado()):
            return
        campos = [("competencia", "Mês de início (MM/AAAA)", "texto"), ("dias", "Dias de gozo", "inteiro"),
                  ("abono", "Dias vendidos (abono)", "inteiro"),
                  ("media", "Média de variáveis (vazio = automática)", "valor_opcional")]
        d = Dialogo(self, f"Férias — {f.nome}", campos,
                    {"competencia": mostrar_competencia(self.app.competencia()), "dias": 30},
                    texto_ok="Calcular", validar=lambda x: ler_competencia(x["competencia"]))
        if not d.resultado:
            return
        r = d.resultado
        comp = ler_competencia(r["competencia"])
        h = servicos.registrar_ferias(self.app.con, f, comp, r["dias"], r["abono"], r["media"])
        aviso = (f"\n\n{r['dias']} dias de férias lançados em {mostrar_competencia(comp)}: o salário do mês "
                 "será proporcional. Se as férias continuarem no mês seguinte, ajuste os dias na aba Lançamentos.")
        JanelaRecibo(self, "Recibo de férias", holerite_texto(f, comp, h, "ferias") + aviso)

    @tratar_erros
    def rescisao(self):
        if not (f := self._selecionado()):
            return
        if not f.ativo:
            raise ValueError("Este funcionário já está desligado.")
        if not f.admissao:
            raise ValueError("Cadastre a data de admissão antes de calcular a rescisão (botão Editar).")
        avisos = {k: NOMES_AVISO[k] for k in sorted({x for v in MOTIVOS.values() for x in v})}
        campos = [("data", "Último dia trabalhado (DD/MM/AAAA)", "data"),
                  ("motivo", "Motivo", "escolha", NOMES_MOTIVO),
                  ("aviso", "Aviso prévio", "escolha", avisos),
                  ("ferias_vencidas", "Períodos de férias vencidas", "inteiro"),
                  ("saldo_fgts", "Saldo da conta FGTS (multa)", "valor"),
                  ("media", "Média de variáveis (vazio = automática)", "valor_opcional"),
                  ("adiantamento_pago", "Adiantamento pago no mês (vazio = automático)", "valor_opcional")]

        def validar(x):
            if not x["data"]:
                raise ValueError("Informe a data do desligamento.")
            if not x["motivo"]:
                raise ValueError("Escolha o motivo.")

        d = Dialogo(self, f"Rescisão — {f.nome}", campos,
                    {"motivo": "sem_justa_causa", "aviso": "indenizado"}, texto_ok="Calcular", validar=validar)
        if not d.resultado:
            return
        r = d.resultado
        aviso = r["aviso"] if r["aviso"] in MOTIVOS[r["motivo"]] else None  # usa o padrão do motivo
        if not messagebox.askyesno("Confirmar rescisão",
                                   f"Calcular a rescisão e DESLIGAR {f.nome}?\n\n"
                                   f"Motivo: {NOMES_MOTIVO[r['motivo']]}\n"
                                   f"Aviso: {NOMES_AVISO[aviso or MOTIVOS[r['motivo']][0]]}"):
            return
        h, projecao, comp = servicos.registrar_rescisao(
            self.app.con, f, date.fromisoformat(r["data"]), r["motivo"], aviso, r["ferias_vencidas"],
            r["saldo_fgts"], r["media"], r["adiantamento_pago"])
        self.atualizar()
        rodape = (f"\n\nMotivo: {NOMES_MOTIVO[r['motivo']]}   Data projetada: {projecao:%d/%m/%Y}\n"
                  "Prazo de pagamento: 10 dias corridos (CLT art. 477 §6º).")
        JanelaRecibo(self, "Termo de rescisão", holerite_texto(f, comp, h, "rescisao") + rodape)


CAMPOS_LANCAMENTO = [
    ("horas_extras_50", "Horas extras 50%", "valor"),
    ("horas_extras_100", "Horas extras 100%", "valor"),
    ("horas_noturnas", "Horas noturnas (22h–5h)", "valor"),
    ("comissoes", "Comissões (R$)", "valor"),
    ("faltas_dias", "Faltas (dias)", "valor"),
    ("dias_ferias", "Dias de férias no mês", "valor"),
    ("feriados", "Feriados fora de domingo", "valor"),
    ("outros_proventos", "Outros proventos (R$)", "valor"),
]
CAMPOS_DESCONTOS = [
    ("desconto_vt", "Vale-transporte (R$)", "valor"),
    ("plano_saude", "Plano de saúde (R$)", "valor"),
    ("plano_odonto", "Plano odontológico (R$)", "valor"),
    ("vale_alimentacao", "Vale-alimentação (R$)", "valor"),
    ("seguro_vida", "Seguro de vida (R$)", "valor"),
    ("emprestimo_consignado", "Empréstimo consignado (R$)", "valor"),
    ("contribuicao_sindical", "Contribuição sindical (R$)", "valor"),
    ("convenio_farmacia", "Convênio farmácia (R$)", "valor"),
    ("outros_descontos", "Outros descontos (R$)", "valor"),
]


class AbaLancamentos(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        barra = barra_competencia(self, app.var_competencia)
        barra.pack(fill="x", pady=(0, 8))
        ttk.Button(barra, text="Carregar", command=self.atualizar).pack(side="left")
        ttk.Label(barra, text="Selecione o funcionário, preencha e salve. Depois processe a folha na aba Folha.",
                  foreground="gray").pack(side="left", padx=12)

        corpo = ttk.Frame(self)
        corpo.pack(fill="both", expand=True)
        self.tabela = Tabela(corpo, [("Matrícula", 70, "center"), ("Nome", 240, "w"),
                                     ("HE 50%", 70, "e"), ("HE 100%", 70, "e"), ("Faltas", 60, "e"),
                                     ("Descontos (R$)", 100, "e")], altura=20)
        self.tabela.pack(side="left", fill="both", expand=True)
        self.tabela.arvore.bind("<<TreeviewSelect>>", lambda e: self.carregar_lancamento())

        lado = ttk.LabelFrame(corpo, text="Lançamentos do mês", padding=8)
        lado.pack(side="left", fill="y", padx=(10, 0))
        self.titulo = ttk.Label(lado, text="—", font=("Segoe UI", 10, "bold"))
        self.titulo.pack(anchor="w", pady=(0, 6))
        abas = ttk.Notebook(lado)
        abas.pack(fill="both")
        self.forms = []
        for titulo, campos in [("Horas e proventos", CAMPOS_LANCAMENTO), ("Descontos", CAMPOS_DESCONTOS)]:
            quadro = ttk.Frame(abas, padding=6)
            abas.add(quadro, text=titulo)
            form = Formulario(quadro, campos, largura=12)
            form.pack(anchor="n")
            self.forms.append(form)
        ttk.Label(lado, text="Vale-transporte: só para quem usa VT (cadastro).\nEm branco, desconta pelo cadastro.",
                  foreground="gray").pack(anchor="w", pady=(6, 0))
        ttk.Button(lado, text="Salvar lançamento", command=self.salvar).pack(fill="x", pady=(10, 0))
        self.atualizar()

    @tratar_erros
    def atualizar(self):
        comp = self.app.competencia()
        linhas = []
        for f in banco.listar_funcionarios(self.app.con):
            l = banco.obter_lancamento(self.app.con, f.id, comp)
            descontos = sum((getattr(l, c[0]) for c in CAMPOS_DESCONTOS), ZERO)
            linhas.append((str(f.id), [f.id, f.nome, numero(l.horas_extras_50) if l.horas_extras_50 else "",
                                       numero(l.horas_extras_100) if l.horas_extras_100 else "",
                                       numero(l.faltas_dias) if l.faltas_dias else "",
                                       numero(descontos) if descontos else ""]))
        self.tabela.preencher(linhas)
        self.titulo.configure(text="—")
        for form in self.forms:
            form.definir({nome: ZERO for nome in form.campos})

    @tratar_erros
    def carregar_lancamento(self):
        if not (iid := self.tabela.selecionado()):
            return
        f = banco.obter_funcionario(self.app.con, int(iid))
        self.titulo.configure(text=f"{f.nome} — {mostrar_competencia(self.app.competencia())}")
        l = banco.obter_lancamento(self.app.con, f.id, self.app.competencia())
        for form in self.forms:
            form.definir(vars(l))

    @tratar_erros
    def salvar(self):
        if not (iid := self.tabela.selecionado()):
            raise ValueError("Selecione um funcionário na lista.")
        l = banco.obter_lancamento(self.app.con, int(iid), self.app.competencia())
        for form in self.forms:
            for campo, v in form.obter().items():
                setattr(l, campo, v)
        if l.desconto_vt and not banco.obter_funcionario(self.app.con, int(iid)).usa_vt:
            raise ValueError("Este funcionário não usa vale-transporte. Marque 'Usa vale-transporte' "
                             "no cadastro ou deixe o desconto de VT em branco.")
        banco.salvar_lancamento(self.app.con, int(iid), self.app.competencia(), l)
        self.atualizar()
        self.tabela.arvore.selection_set(iid)


class AbaFolha(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        barra = barra_competencia(self, app.var_competencia)
        barra.pack(fill="x")
        ttk.Label(barra, text="Folha:").pack(side="left")
        self.var_folha = tk.StringVar(value=NOMES_FOLHA["mensal"])
        combo = ttk.Combobox(barra, textvariable=self.var_folha, values=list(NOMES_FOLHA.values()),
                             state="readonly", width=18)
        combo.pack(side="left", padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self.atualizar())
        ttk.Button(barra, text="Mostrar", command=self.atualizar).pack(side="left", padx=4)

        acoes = ttk.Frame(self)
        acoes.pack(fill="x", pady=8)
        ttk.Button(acoes, text="Processar folha mensal", command=self.processar).pack(side="left")
        ttk.Button(acoes, text="13º 1ª parcela", command=lambda: self.decimo(1)).pack(side="left", padx=6)
        ttk.Button(acoes, text="13º 2ª parcela", command=lambda: self.decimo(2)).pack(side="left")
        ttk.Button(acoes, text="Adiantamento quinzenal", command=self.adiantamento).pack(side="left", padx=6)
        ttk.Button(acoes, text="Exportar CSV", command=self.exportar).pack(side="right")
        ttk.Button(acoes, text="Data de pagamento...", command=self.data_pagamento).pack(side="right", padx=6)
        ttk.Button(acoes, text="Imprimir todos", command=self.imprimir_todos).pack(side="right", padx=6)
        ttk.Button(acoes, text="Ver recibo", command=self.ver_recibo).pack(side="right")

        self.tabela = Tabela(self, [("Matrícula", 70, "center"), ("Nome", 260, "w"), ("Proventos", 120, "e"),
                                    ("Descontos", 120, "e"), ("Líquido", 120, "e"), ("FGTS", 100, "e")], altura=20)
        self.tabela.pack(fill="both", expand=True)
        self.tabela.arvore.bind("<Double-1>", lambda e: self.ver_recibo())
        self.resultados = []

    def folha(self) -> str:
        return next(k for k, v in NOMES_FOLHA.items() if v == self.var_folha.get())

    def _mostrar(self, resultados):
        self.resultados = resultados
        soma = lambda attr: numero(sum((getattr(h, attr) for _, h in resultados), ZERO))
        self.tabela.preencher(
            [(str(f.id), [f.id, f.nome, numero(h.total_proventos), numero(h.total_descontos),
                          numero(h.liquido), numero(h.fgts)]) for f, h in resultados],
            ["", f"TOTAL ({len(resultados)})", soma("total_proventos"), soma("total_descontos"),
             soma("liquido"), soma("fgts")] if resultados else None)

    @tratar_erros
    def atualizar(self):
        self._mostrar(servicos.resumo(self.app.con, self.app.competencia(), self.folha()))

    @tratar_erros
    def processar(self):
        comp = self.app.competencia()
        if servicos.resumo(self.app.con, comp, "mensal") and not messagebox.askyesno(
                "Reprocessar", f"A folha de {mostrar_competencia(comp)} já foi processada. Recalcular?"):
            return
        self.var_folha.set(NOMES_FOLHA["mensal"])
        self._mostrar(servicos.processar_mensal(self.app.con, comp))

    @tratar_erros
    def decimo(self, parcela: int):
        ano = int(self.app.competencia()[:4])
        if not messagebox.askyesno("13º salário", f"Calcular a {parcela}ª parcela do 13º de {ano} "
                                   f"para todos os funcionários ativos?"):
            return
        comp, resultados = servicos.processar_decimo(self.app.con, ano, parcela)
        self.app.var_competencia.set(mostrar_competencia(comp))
        self.var_folha.set(NOMES_FOLHA[f"13-{parcela}"])
        self._mostrar(resultados)

    @tratar_erros
    def adiantamento(self):
        lista = servicos.adiantamentos(self.app.con)
        if not lista:
            raise ValueError("Nenhum funcionário com adiantamento quinzenal (defina o % no cadastro).")
        linhas = [f"ADIANTAMENTO QUINZENAL — {mostrar_competencia(self.app.competencia())}", ""]
        linhas += [f"{f.id:>4}  {f.nome:<34}{f.adiantamento_pct:>5}%  {numero(v):>14}" for f, v in lista]
        linhas += ["", f"{'TOTAL':<46}{numero(sum((v for _, v in lista), ZERO)):>14}", "",
                   "O valor é descontado automaticamente na folha mensal."]
        JanelaRecibo(self, "Adiantamento quinzenal", "\n".join(linhas))

    def _recibo(self, f, h) -> str:
        return holerite_texto(f, self.app.competencia(), h, self.folha())

    @tratar_erros
    def ver_recibo(self):
        iid = self.tabela.selecionado()
        par = next(((f, h) for f, h in self.resultados if str(f.id) == iid), None)
        if not par:
            raise ValueError("Selecione um funcionário na lista.")
        JanelaRecibo(self, f"Recibo {NOMES_FOLHA[self.folha()]} — {par[0].nome}", self._recibo(*par))

    @tratar_erros
    def imprimir_todos(self):
        if not self.resultados:
            raise ValueError("Nada para imprimir. Processe ou mostre uma folha primeiro.")
        imprimir_texto("\f".join(self._recibo(f, h) for f, h in self.resultados))  # \f = nova página

    @tratar_erros
    def data_pagamento(self):
        comp, folha = self.app.competencia(), self.folha()
        atual = es_servico.data_pagamento(self.app.con, comp, folha)

        def validar(x):
            if not x["data"]:
                raise ValueError("Informe a data do pagamento.")

        d = Dialogo(self, f"Pagamento — {NOMES_FOLHA[folha]} {mostrar_competencia(comp)}",
                    [("data", "Data do pagamento (DD/MM/AAAA)", "data")],
                    {"data": atual.isoformat() if atual else ""}, validar=validar)
        if d.resultado:
            es_servico.definir_data_pagamento(self.app.con, comp, folha, date.fromisoformat(d.resultado["data"]))
            messagebox.showinfo("Data de pagamento", "Data salva. Ela define em qual mês o pagamento vai "
                                "para o eSocial (S-1210).")

    @tratar_erros
    def exportar(self):
        if not self.resultados:
            raise ValueError("Nada para exportar.")
        nome = f"folha_{self.folha()}_{self.app.competencia()}.csv"
        if caminho := filedialog.asksaveasfilename(parent=self, initialfile=nome, defaultextension=".csv",
                                                   filetypes=[("CSV (Excel)", "*.csv")]):
            exportar_resumo_csv(Path(caminho), self.resultados)
            messagebox.showinfo("Exportar", f"Arquivo salvo em:\n{caminho}")


class AbaEncargos(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        barra = barra_competencia(self, app.var_competencia)
        barra.pack(fill="x", pady=(0, 8))
        ttk.Button(barra, text="Calcular", command=self.atualizar).pack(side="left")
        ttk.Button(barra, text="Exportar CSV", command=self.exportar).pack(side="right")
        self.regime = ttk.Label(barra, foreground="gray")
        self.regime.pack(side="left", padx=12)

        ttk.Label(self, text="Custo por funcionário (folha mensal + provisões)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.area_custos = ttk.Frame(self)
        self.area_custos.pack(fill="both", expand=True, pady=(4, 10))
        ttk.Label(self, text="Valores a recolher na competência (todas as folhas)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.guias = Tabela(self, [("Guia", 360, "w"), ("Valor", 140, "e")], altura=8)
        self.guias.pack(fill="x", pady=(4, 0))
        self.custos = []
        self.tabela = None

    @tratar_erros
    def atualizar(self):
        comp = self.app.competencia()
        self.custos, guias = servicos.encargos(self.app.con, comp)
        self.regime.configure(text="Regime: " + ("Simples Nacional" if tabelas.EMPRESA_SIMPLES_NACIONAL
                                                  else "Lucro Presumido/Real") + " (altere em Configurações)")
        if self.tabela:
            self.tabela.destroy()
        colunas = list(self.custos[0][1]) if self.custos else []
        self.tabela = Tabela(self.area_custos, [("Nome", 200, "w")] + [(c, 95, "e") for c in colunas], altura=10)
        self.tabela.pack(fill="both", expand=True)
        totais = {c: sum((x[c] for _, x in self.custos), ZERO) for c in colunas}
        self.tabela.preencher([(str(f.id), [f.nome, *(numero(c[k]) for k in colunas)]) for f, c in self.custos],
                              ["TOTAL", *(numero(totais[k]) for k in colunas)] if self.custos else None)
        self.guias.preencher([(str(i), [desc, numero(v)]) for i, (desc, v) in enumerate(guias.items())])
        if not self.custos and not any(guias.values()):
            messagebox.showinfo("Encargos", f"Nada processado em {mostrar_competencia(comp)}.")

    @tratar_erros
    def exportar(self):
        if not self.custos:
            raise ValueError("Calcule os encargos primeiro.")
        if caminho := filedialog.asksaveasfilename(parent=self, initialfile=f"custos_{self.app.competencia()}.csv",
                                                   defaultextension=".csv", filetypes=[("CSV (Excel)", "*.csv")]):
            exportar_custos_csv(Path(caminho), self.custos)
            messagebox.showinfo("Exportar", f"Arquivo salvo em:\n{caminho}")


CAMPOS_EMPRESA = [
    ("EMPRESA_NOME", "Razão social", "texto"),
    ("EMPRESA_CNPJ", "CNPJ", "texto"),
    ("ALIQUOTA_INSS_PATRONAL", "INSS patronal (%)", "percentual"),
    ("ALIQUOTA_RAT", "RAT (%)", "percentual"),
    ("FAP", "FAP", "decimal"),
    ("ALIQUOTA_TERCEIROS", "Terceiros (%)", "percentual"),
    ("EMPRESA_SIMPLES_NACIONAL", "Optante pelo Simples Nacional (sem INSS patronal)", "bool"),
]


class AbaConfiguracoes(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        quadro = ttk.LabelFrame(self, text="Dados da empresa", padding=10)
        quadro.pack(fill="x")
        self.form = Formulario(quadro, CAMPOS_EMPRESA, largura=40)
        self.form.pack(anchor="w")
        ttk.Button(quadro, text="Salvar dados da empresa", command=self.salvar).pack(anchor="w", pady=(8, 0))

        quadro = ttk.LabelFrame(self, text="Tabelas legais (INSS, IRRF, salário mínimo...)", padding=10)
        quadro.pack(fill="x", pady=10)
        ttk.Label(quadro, wraplength=760, justify="left", text=(
            "As tabelas mudam todo ano. Para atualizar, abra o arquivo de tabelas, altere os valores, "
            "salve e clique em Recarregar. Alíquotas em fração (0.075 = 7,5%).")).pack(anchor="w")
        botoes = ttk.Frame(quadro)
        botoes.pack(anchor="w", pady=(8, 0))
        ttk.Button(botoes, text="Abrir arquivo de tabelas",
                   command=lambda: os.startfile(config.caminho_tabelas())).pack(side="left")
        ttk.Button(botoes, text="Recarregar", command=self.recarregar).pack(side="left", padx=6)
        ttk.Button(botoes, text="Rubricas do eSocial", command=self.abrir_rubricas).pack(side="left")
        self.resumo_tabelas = ttk.Label(quadro, foreground="gray")
        self.resumo_tabelas.pack(anchor="w", pady=(8, 0))

        quadro = ttk.LabelFrame(self, text="Dados e cópia de segurança", padding=10)
        quadro.pack(fill="x")
        ttk.Label(quadro, text=f"Pasta de dados: {config.pasta_dados()}").pack(anchor="w")
        ttk.Label(quadro, foreground="gray", wraplength=760, justify="left", text=(
            "Para levar os dados a outro computador, copie esta pasta inteira para Documentos\\FolhaPagamento "
            "no outro computador.")).pack(anchor="w")
        botoes = ttk.Frame(quadro)
        botoes.pack(anchor="w", pady=(8, 0))
        ttk.Button(botoes, text="Fazer backup...", command=self.backup).pack(side="left")
        ttk.Button(botoes, text="Abrir pasta de dados",
                   command=lambda: os.startfile(config.pasta_dados())).pack(side="left", padx=6)
        ttk.Label(self, text=f"Folha de Pagamento {VERSAO} — funciona sem internet.",
                  foreground="gray").pack(anchor="w", pady=(10, 0))
        self.carregar()

    def carregar(self):
        self.form.definir({c[0]: getattr(tabelas, c[0]) for c in CAMPOS_EMPRESA})
        self.resumo_tabelas.configure(text=(
            f"Em uso: salário mínimo R$ {numero(tabelas.SALARIO_MINIMO)}  •  "
            f"teto INSS R$ {numero(tabelas.TABELA_INSS[-1][0])}  •  "
            f"isenção IR até R$ {numero(tabelas.REDUCAO_IR_LIMITE_ISENCAO)}"))

    @tratar_erros
    def salvar(self):
        for nome, v in self.form.obter().items():
            setattr(tabelas, nome, v)
        config.salvar_tabelas()
        self.carregar()
        self.app.atualizar_titulo()
        messagebox.showinfo("Configurações", "Dados da empresa salvos.")

    @tratar_erros
    def abrir_rubricas(self):
        es_rubricas.carregar()  # cria o arquivo com a tabela padrão na primeira vez
        os.startfile(es_rubricas.caminho())

    @tratar_erros
    def recarregar(self):
        config.carregar_tabelas()
        self.carregar()
        self.app.atualizar_titulo()
        messagebox.showinfo("Configurações", "Tabelas recarregadas.")

    @tratar_erros
    def backup(self):
        nome = f"folha_backup_{datetime.now():%Y%m%d_%H%M}.db"
        if caminho := filedialog.asksaveasfilename(parent=self, initialfile=nome, defaultextension=".db",
                                                   filetypes=[("Banco de dados", "*.db")]):
            import sqlite3
            with sqlite3.connect(caminho) as destino:
                self.app.con.backup(destino)  # cópia consistente mesmo com o banco aberto
            messagebox.showinfo("Backup", f"Backup salvo em:\n{caminho}")


CAMPOS_ESOCIAL = [
    ("ESOCIAL_AMBIENTE", "Ambiente", "escolha", AMBIENTES),
    ("ESOCIAL_COD_LOTACAO", "Código da lotação tributária (S-1020)", "texto"),
    ("ESOCIAL_CNPJ_ESTABELECIMENTO", "CNPJ do estabelecimento (vazio = o da empresa)", "texto"),
    ("ESOCIAL_TAB_RUBRICAS", "Identificador da tabela de rubricas", "texto"),
    ("ESOCIAL_INICIO_RUBRICAS", "Primeira competência neste programa (MM/AAAA)", "competencia"),
]


def tratar_esocial(fn):
    """Como tratar_erros, mostrando também falhas de comunicação com o eSocial."""
    @functools.wraps(fn)
    def envolvida(self, *args, **kwargs):
        try:
            self.winfo_toplevel().configure(cursor="watch")
            self.update()
            return fn(self, *args, **kwargs)
        except ErroComunicacao as e:
            messagebox.showerror("Comunicação com o eSocial", str(e))
        except ValueError as e:
            messagebox.showerror("eSocial", str(e))
        except Exception:
            messagebox.showerror("Erro inesperado", traceback.format_exc(limit=3))
        finally:
            self.winfo_toplevel().configure(cursor="")
    return envolvida


class AbaESocial(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app = app
        barra = barra_competencia(self, app.var_competencia)
        barra.pack(fill="x")
        ttk.Button(barra, text="Atualizar", command=self.atualizar).pack(side="left")
        ttk.Button(barra, text="Configurar...", command=self.configurar).pack(side="right")
        ttk.Button(barra, text="Certificado A1...", command=self.escolher_certificado).pack(side="right", padx=6)
        self.rotulo_ambiente = ttk.Label(barra, font=("Segoe UI", 9, "bold"))
        self.rotulo_ambiente.pack(side="right", padx=12)

        acoes = ttk.Frame(self)
        acoes.pack(fill="x", pady=8)
        ttk.Button(acoes, text="1. Gerar eventos", command=self.gerar).pack(side="left")
        ttk.Button(acoes, text="2. Enviar próxima etapa", command=self.enviar).pack(side="left", padx=6)
        ttk.Button(acoes, text="3. Consultar retornos", command=self.consultar).pack(side="left")
        ttk.Button(acoes, text="Pagamentos do sistema anterior...", command=self.importar).pack(side="right")
        ttk.Button(acoes, text="Exportar XMLs...", command=self.exportar).pack(side="right", padx=6)
        ttk.Button(acoes, text="Ver detalhes", command=self.detalhes).pack(side="right")
        self.rotulo_etapa = ttk.Label(self, foreground="gray")
        self.rotulo_etapa.pack(anchor="w", pady=(0, 6))

        self.tabela = Tabela(self, [("Evento", 70, "center"), ("Referente a", 260, "w"), ("Situação", 130, "center"),
                                    ("Recibo", 200, "w"), ("Mensagem do eSocial", 420, "w")], altura=18)
        self.tabela.pack(fill="both", expand=True)
        self.tabela.arvore.tag_configure("rejeitado", foreground="#b00020")
        self.tabela.arvore.tag_configure("aceito", foreground="#1b7f3b")
        self.tabela.arvore.bind("<Double-1>", lambda e: self.detalhes())

    def _ambiente(self) -> int:
        return int(tabelas.ESOCIAL_AMBIENTE)

    @tratar_erros
    def atualizar(self):
        comp, amb = self.app.competencia(), self._ambiente()
        producao = amb == 1
        self.rotulo_ambiente.configure(text="Ambiente: PRODUÇÃO (oficial)" if producao else
                                       "Ambiente: produção restrita (testes)",
                                       foreground="#b00020" if producao else "#1f5fa8")
        linhas = es_servico.listar(self.app.con, comp, amb)
        self.tabela.preencher([])
        for r in linhas:
            if r["tipo"] == "S-1010":
                referente = f"Rubrica {r['chave'].split('|')[-1]}"
            elif r["tipo"] == "S-1299":
                referente = f"Fechamento de {mostrar_competencia(comp)}"
            else:
                referente = r["nome"] or f"CPF {r['chave'].split('|')[-1]}"
            mensagem = (r["mensagens"] or "").split("\n")[0]
            self.tabela.arvore.insert("", "end", iid=str(r["id"]), tags=(r["status"],), values=[
                r["tipo"], referente, SITUACOES.get(r["status"], r["status"]), r["recibo"] or "", mensagem])
        etapa = es_servico.proxima_etapa(self.app.con, comp, amb)
        aguardando = any(r["status"] == "enviado" for r in linhas)
        rejeitados = sum(r["status"] == "rejeitado" for r in linhas)
        self.rotulo_etapa.configure(text=(
            "Lote enviado: aguarde alguns minutos e clique em 3. Consultar retornos." if aguardando else
            f"{rejeitados} evento(s) rejeitado(s): veja a mensagem (duplo clique), corrija o cadastro ou a folha "
            "e clique em 1. Gerar eventos." if rejeitados else
            f"Próximo passo: enviar {etapa}." if etapa else
            "Nada pendente. Depois de processar a folha e definir as datas de pagamento, clique em 1. Gerar eventos."))

    @tratar_erros
    def configurar(self):
        atuais = {c[0]: getattr(tabelas, c[0]) for c in CAMPOS_ESOCIAL}
        d = Dialogo(self, "Configuração do eSocial", CAMPOS_ESOCIAL, atuais)
        if not d.resultado:
            return
        if d.resultado["ESOCIAL_AMBIENTE"] == 1 and atuais["ESOCIAL_AMBIENTE"] != 1 and not messagebox.askyesno(
                "Ambiente de produção", "No ambiente de PRODUÇÃO os eventos têm valor legal e substituem as "
                "informações enviadas pelo sistema anterior.\n\nUse-o somente depois de testar na produção "
                "restrita e conferir os resultados com o contador. Mudar para produção?", icon="warning"):
            return
        for nome, v in d.resultado.items():
            setattr(tabelas, nome, v)
        config.salvar_tabelas()
        self.atualizar()

    @tratar_erros
    def escolher_certificado(self):
        if caminho := filedialog.askopenfilename(parent=self, title="Certificado digital A1",
                                                 filetypes=[("Certificado A1", "*.pfx *.p12")]):
            tabelas.ESOCIAL_CERTIFICADO = caminho
            config.salvar_tabelas()
            self.app.certificado = None
            messagebox.showinfo("Certificado", f"Certificado selecionado:\n{caminho}\n\nA senha será pedida "
                                "no primeiro envio e fica guardada só enquanto o programa estiver aberto.")

    def _certificado(self):
        if self.app.certificado:
            return self.app.certificado
        caminho = tabelas.ESOCIAL_CERTIFICADO
        if not caminho or not Path(caminho).exists():
            raise ValueError("Selecione o arquivo do certificado A1 (botão Certificado A1...).")
        senha = simpledialog.askstring("Certificado digital", f"Senha do certificado:\n{Path(caminho).name}",
                                       show="*", parent=self)
        if senha is None:
            return None
        cert = es_assinatura.carregar_pfx(caminho, senha)
        dias = (cert.validade - datetime.now(cert.validade.tzinfo)).days
        if dias < 30:
            messagebox.showwarning("Certificado", f"O certificado vence em {dias} dia(s) "
                                   f"({cert.validade:%d/%m/%Y}). Providencie a renovação.")
        self.app.certificado = cert
        return cert

    @tratar_esocial
    def gerar(self):
        comp = self.app.competencia()
        r = es_servico.gerar(self.app.con, comp)
        total = sum(r.gerados.values())
        texto = (f"{total} evento(s) gerado(s) para {mostrar_competencia(comp)}:\n" +
                 "\n".join(f"  {t}: {n}" for t, n in r.gerados.items() if n)) if total else \
            "Nenhum evento novo: tudo o que existe já foi gerado ou aceito."
        if r.avisos:
            texto += "\n\nAtenção:\n" + "\n".join(f"• {a}" for a in r.avisos)
        self.atualizar()
        (messagebox.showwarning if r.avisos else messagebox.showinfo)("Gerar eventos", texto)

    @tratar_esocial
    def enviar(self):
        comp, amb = self.app.competencia(), self._ambiente()
        etapa = es_servico.proxima_etapa(self.app.con, comp, amb)
        if not etapa:
            raise ValueError("Nenhum evento pendente de envio. Clique em 1. Gerar eventos.")
        aviso = "\n\nATENÇÃO: ambiente de PRODUÇÃO — os dados têm valor legal." if amb == 1 else ""
        if not messagebox.askyesno("Enviar ao eSocial", f"Enviar os eventos {etapa} de "
                                   f"{mostrar_competencia(comp)}?{aviso}", icon="warning" if amb == 1 else "question"):
            return
        if not (cert := self._certificado()):
            return
        r = es_servico.enviar(self.app.con, comp, cert)
        self.atualizar()
        messagebox.showinfo("Enviado", f"{r.eventos} evento(s) {r.etapa} enviados em {len(r.protocolos)} lote(s).\n"
                            f"Protocolo(s): {', '.join(r.protocolos)}\n\nO eSocial processa em alguns minutos. "
                            "Depois clique em 3. Consultar retornos.")

    @tratar_esocial
    def consultar(self):
        if not (cert := self._certificado()):
            return
        mensagens = es_servico.consultar(self.app.con, cert)
        self.atualizar()
        messagebox.showinfo("Retorno do eSocial", "\n".join(mensagens))

    @tratar_erros
    def detalhes(self):
        if not (iid := self.tabela.selecionado()):
            raise ValueError("Selecione um evento na lista.")
        r = self.app.con.execute("SELECT * FROM esocial_eventos WHERE id = ?", (int(iid),)).fetchone()
        xml = etree.tostring(etree.fromstring(r["xml"].encode()), pretty_print=True, encoding="unicode")
        texto = (f"Evento: {r['tipo']}   Situação: {SITUACOES.get(r['status'], r['status'])}\n"
                 f"Id: {r['id_evento']}\nProtocolo: {r['protocolo'] or '-'}\nRecibo: {r['recibo'] or '-'}\n"
                 f"Atualizado em: {r['atualizado']}\n\nMensagens do eSocial:\n{r['mensagens'] or '-'}\n\n"
                 f"XML:\n{xml}")
        JanelaRecibo(self, f"{r['tipo']} — detalhes", texto)

    @tratar_erros
    def exportar(self):
        if pasta := filedialog.askdirectory(parent=self, title="Pasta para salvar os XMLs"):
            n = es_servico.exportar_xmls(self.app.con, self.app.competencia(), self._ambiente(), Path(pasta))
            messagebox.showinfo("Exportar XMLs", f"{n} arquivo(s) salvos em:\n{pasta}")

    @tratar_erros
    def importar(self):
        messagebox.showinfo("Pagamentos do sistema anterior", (
            "Use na transição: quando este programa pagar (S-1210) uma folha calculada no sistema anterior.\n\n"
            "Arquivo CSV separado por ponto e vírgula, com o cabeçalho:\n"
            "cpf;data;competencia;ide_dm_dev;valor\n\n"
            "Exemplo:\n529.982.247-25;05/11/2026;10/2026;CODIGO-DO-SISTEMA-ANTERIOR;2.345,67\n\n"
            "ide_dm_dev é o identificador do demonstrativo enviado pelo sistema anterior no S-1200 "
            "(peça ao fornecedor ou consulte no portal do eSocial)."))
        if caminho := filedialog.askopenfilename(parent=self, filetypes=[("CSV", "*.csv")]):
            n = es_servico.importar_pagamentos_externos(self.app.con, Path(caminho))
            messagebox.showinfo("Pagamentos do sistema anterior", f"{n} pagamento(s) importado(s).")


# --- janela principal ---------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1150x700")
        self.minsize(950, 560)
        try:
            config.carregar_tabelas()
        except ValueError as e:
            messagebox.showerror("Tabelas", f"{e}\n\nOs valores padrão serão usados.")
        self.con = banco.conectar()
        self.certificado = None  # certificado A1 aberto nesta sessão (só em memória)
        hoje = date.today()
        self.var_competencia = tk.StringVar(value=f"{hoje.month:02d}/{hoje.year}")

        abas = ttk.Notebook(self)
        abas.pack(fill="both", expand=True, padx=6, pady=6)
        self.abas = [
            ("Funcionários", AbaFuncionarios(abas, self)),
            ("Lançamentos", AbaLancamentos(abas, self)),
            ("Folha", AbaFolha(abas, self)),
            ("Encargos e guias", AbaEncargos(abas, self)),
            ("eSocial", AbaESocial(abas, self)),
            ("Configurações", AbaConfiguracoes(abas, self)),
        ]
        for nome, aba in self.abas:
            abas.add(aba, text=nome)
        abas.bind("<<NotebookTabChanged>>", self._ao_trocar_aba)
        self.atualizar_titulo()
        self.protocol("WM_DELETE_WINDOW", self.fechar)

    def competencia(self) -> str:
        return ler_competencia(self.var_competencia.get())

    def atualizar_titulo(self):
        empresa = f" — {tabelas.EMPRESA_NOME}" if tabelas.EMPRESA_NOME else ""
        self.title(f"Folha de Pagamento{empresa}")

    def _ao_trocar_aba(self, evento):
        aba = evento.widget.nametowidget(evento.widget.select())
        if isinstance(aba, (AbaFuncionarios, AbaLancamentos, AbaESocial)):
            aba.atualizar()

    def fechar(self):
        self.con.close()
        self.destroy()


def main():
    if sys.platform == "win32":
        try:  # texto nítido em telas com escala (125%, 150%)
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
