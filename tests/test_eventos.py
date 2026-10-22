import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from folha import banco
from folha.calculo import Funcionario, Lancamento, calcular_folha, calcular_inss
from folha.datas import avos_13, avos_ferias
from folha.decimo_terceiro import primeira_parcela, segunda_parcela
from folha.encargos import custo_mensal, totais_guias
from folha.ferias import calcular_ferias
from folha.rescisao import calcular_rescisao, dias_aviso_previo


class TestEventosMensais(unittest.TestCase):
    def test_dsr_sobre_horas_extras(self):
        # Out/2026: 4 domingos + feriado de 12/10 = 5 dias de descanso, 26 úteis
        f = Funcionario(nome="Ana", salario=D("2200"))
        h = calcular_folha(f, Lancamento(horas_extras_50=D("10"), feriados=D("1")), "2026-10")
        self.assertEqual(h.proventos["DSR sobre variáveis"], D("28.85"))  # 150 / 26 * 5

    def test_periculosidade_prevalece_e_entra_na_hora_extra(self):
        f = Funcionario(nome="Beto", salario=D("2000"), periculosidade=True, insalubridade=20)
        h = calcular_folha(f, Lancamento(horas_extras_50=D("10")))
        self.assertEqual(h.proventos["Adicional de periculosidade"], D("600.00"))
        self.assertNotIn("Adicional de insalubridade 20%", h.proventos)
        self.assertEqual(h.proventos["Horas extras 50%"], D("177.27"))  # 2600/220 * 1,5 * 10

    def test_insalubridade_sobre_salario_minimo(self):
        h = calcular_folha(Funcionario(nome="Caio", salario=D("2000"), insalubridade=40))
        self.assertEqual(h.proventos["Adicional de insalubridade 40%"], D("648.40"))

    def test_adicional_noturno_com_hora_reduzida(self):
        h = calcular_folha(Funcionario(nome="Duda", salario=D("2200")), Lancamento(horas_noturnas=D("35")))
        self.assertEqual(h.proventos["Adicional noturno"], D("80.00"))  # 10 * 20% * 35 * 8/7

    def test_salario_familia_nao_entra_na_base(self):
        h = calcular_folha(Funcionario(nome="Eva", salario=D("1700"), filhos_sf=2))
        self.assertEqual(h.proventos["Salário-família"], D("135.08"))
        self.assertEqual(h.base_inss, D("1700"))

    def test_adiantamento_e_vr(self):
        h = calcular_folha(Funcionario(nome="Fabi", salario=D("3000"), adiantamento_pct=D("40"),
                                       desconto_vr=D("50")))
        self.assertEqual(h.descontos["Adiantamento salarial"], D("1200.00"))
        self.assertEqual(h.descontos["Vale-refeição"], D("50.00"))

    def test_descontos_do_mes(self):
        f = Funcionario(nome="Hugo", salario=D("3000"), usa_vt=True, valor_vt=D("400"))
        h = calcular_folha(f, Lancamento(plano_saude=D("250"), seguro_vida=D("15.5")))
        self.assertEqual(h.descontos["Vale-transporte"], D("180.00"))  # 6% do salário (cadastro)
        self.assertEqual(h.descontos["Plano de saúde"], D("250.00"))
        self.assertEqual(h.descontos["Seguro de vida"], D("15.50"))
        self.assertEqual(h.base_inss, D("3000"))  # descontos não alteram as bases

        h = calcular_folha(f, Lancamento(desconto_vt=D("90")))
        self.assertEqual(h.descontos["Vale-transporte"], D("90.00"))  # lançamento substitui o cadastro

    def test_sem_vale_transporte_nao_desconta(self):
        f = Funcionario(nome="Iara", salario=D("3000"), usa_vt=False, valor_vt=D("400"))
        h = calcular_folha(f, Lancamento(desconto_vt=D("90")))
        self.assertNotIn("Vale-transporte", h.descontos)

    def test_migracao_marca_vt_de_quem_tinha_valor(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            caminho = Path(d) / "antigo.db"
            con = sqlite3.connect(caminho)
            con.execute("CREATE TABLE funcionarios (id INTEGER PRIMARY KEY, nome TEXT, cpf TEXT UNIQUE, cargo TEXT,"
                        " admissao TEXT, salario TEXT, dependentes INTEGER DEFAULT 0,"
                        " valor_vt TEXT NOT NULL DEFAULT '0', pensao TEXT NOT NULL DEFAULT '0',"
                        " ativo INTEGER NOT NULL DEFAULT 1)")
            con.execute("INSERT INTO funcionarios (nome, salario, valor_vt) VALUES ('A', '2000', '250'), ('B', '2000', '0')")
            con.commit()
            con.close()
            con = banco.conectar(caminho)
            self.assertEqual([f.usa_vt for f in banco.listar_funcionarios(con)], [True, False])
            con.close()

    def test_mes_com_ferias_consolida_inss(self):
        f = Funcionario(nome="Gil", salario=D("3000"))
        ferias = calcular_ferias(f, dias=20)
        h = calcular_folha(f, Lancamento(dias_ferias=D("20")), None,
                           ferias.base_inss, ferias.descontos["INSS"])
        self.assertEqual(h.proventos["Salário (10 dias)"], D("1000.00"))
        inss_total = calcular_inss(ferias.base_inss + h.base_inss)
        self.assertEqual(h.descontos["INSS"] + ferias.descontos["INSS"], inss_total)


class TestDatas(unittest.TestCase):
    def test_avos_13(self):
        self.assertEqual(avos_13(date(2026, 3, 20), date(2026, 12, 31), 2026), 9)   # março com 12 dias
        self.assertEqual(avos_13(date(2026, 3, 17), date(2026, 12, 31), 2026), 10)  # março com 15 dias
        self.assertEqual(avos_13(date(2020, 1, 1), date(2026, 12, 31), 2026), 12)

    def test_avos_ferias(self):
        self.assertEqual(avos_ferias(date(2025, 3, 10), date(2025, 7, 25)), 5)
        self.assertEqual(avos_ferias(date(2025, 3, 10), date(2025, 7, 20)), 4)
        self.assertEqual(avos_ferias(date(2025, 3, 10), date(2026, 3, 9)), 12)

    def test_aviso_previo_proporcional(self):
        self.assertEqual(dias_aviso_previo(date(2023, 2, 1), date(2026, 10, 15)), 39)
        self.assertEqual(dias_aviso_previo(date(1990, 1, 1), date(2026, 10, 15)), 90)


class TestFerias(unittest.TestCase):
    def test_ferias_30_dias(self):
        h = calcular_ferias(Funcionario(nome="Ana", salario=D("3000")))
        self.assertEqual(h.proventos["1/3 constitucional de férias"], D("1000.00"))
        self.assertEqual(h.descontos["INSS"], D("368.60"))
        self.assertNotIn("IRRF", h.descontos)
        self.assertEqual(h.fgts, D("320.00"))

    def test_abono_pecuniario_isento(self):
        h = calcular_ferias(Funcionario(nome="Ana", salario=D("3000")), dias=20, abono=10)
        self.assertEqual(h.proventos["Abono pecuniário (10 dias)"], D("1000.00"))
        self.assertEqual(h.base_inss, D("2666.67"))

    def test_limites(self):
        f = Funcionario(nome="Ana", salario=D("3000"))
        with self.assertRaises(ValueError):
            calcular_ferias(f, dias=25, abono=10)


class TestDecimoTerceiro(unittest.TestCase):
    def test_parcelas(self):
        f = Funcionario(nome="Ana", salario=D("3000"))
        p1 = primeira_parcela(f, 12)
        self.assertEqual(p1.liquido, D("1500.00"))
        p2 = segunda_parcela(f, 12, primeira_paga=p1.liquido)
        self.assertEqual(p2.descontos["INSS 13º"], D("248.60"))
        self.assertEqual(p2.liquido, D("1251.40"))
        self.assertEqual(p2.fgts, D("120.00"))

    def test_irrf_exclusivo_sem_desconto_simplificado(self):
        p2 = segunda_parcela(Funcionario(nome="Rui", salario=D("10000")), 12)
        self.assertEqual(p2.descontos["IRRF 13º"], D("1569.55"))  # (10000 - 988,09) * 27,5% - 908,73


class TestRescisao(unittest.TestCase):
    def test_dispensa_sem_justa_causa(self):
        f = Funcionario(nome="Ana", salario=D("3000"))
        h, projecao = calcular_rescisao(f, date(2023, 2, 1), date(2026, 10, 15), "sem_justa_causa",
                                        saldo_fgts=D("10000"))
        self.assertEqual(projecao, date(2026, 11, 23))
        p = h.proventos
        self.assertEqual(p["Saldo de salário (15 dias)"], D("1500.00"))
        self.assertEqual(p["Aviso prévio indenizado (39 dias)"], D("3900.00"))
        self.assertEqual(p["13º salário proporcional (11/12)"], D("2750.00"))
        self.assertEqual(p["Férias proporcionais (10/12)"], D("2500.00"))
        self.assertEqual(h.descontos["INSS"], D("112.50"))
        self.assertEqual(h.descontos["INSS 13º"], D("223.19"))
        self.assertEqual(h.fgts, D("652.00"))
        self.assertEqual(h.bases["Multa FGTS 40% (guia rescisória)"], D("4260.80"))

    def test_justa_causa_so_saldo_e_vencidas(self):
        f = Funcionario(nome="Ana", salario=D("3000"))
        h, _ = calcular_rescisao(f, date(2023, 2, 1), date(2026, 10, 15), "justa_causa", ferias_vencidas=1)
        self.assertEqual(set(h.proventos), {"Saldo de salário (15 dias)", "Férias vencidas (1 período(s))",
                                            "1/3 sobre férias vencidas"})

    def test_pedido_sem_cumprir_aviso(self):
        f = Funcionario(nome="Ana", salario=D("3000"))
        h, projecao = calcular_rescisao(f, date(2025, 1, 10), date(2026, 10, 31), "pedido_demissao",
                                        aviso="nao_cumprido")
        self.assertEqual(projecao, date(2026, 10, 31))
        self.assertEqual(h.descontos["Aviso prévio não cumprido (30 dias)"], D("3000.00"))
        self.assertEqual(h.proventos["Saldo de salário (30 dias)"], D("3000.00"))
        self.assertNotIn("Multa FGTS 40% (guia rescisória)", h.bases)

    def test_acordo_paga_metade_do_aviso(self):
        f = Funcionario(nome="Ana", salario=D("3000"))
        h, _ = calcular_rescisao(f, date(2025, 1, 10), date(2026, 10, 15), "acordo")
        self.assertEqual(h.proventos["Aviso prévio indenizado (33 dias)"], D("1650.00"))
        self.assertIn("Multa FGTS 20% (guia rescisória)", h.bases)


class TestEncargos(unittest.TestCase):
    def test_custo_e_guias(self):
        f = Funcionario(nome="Ana", salario=D("3000"), filhos_sf=0)
        h = calcular_folha(f)
        c = custo_mensal(f, h)
        self.assertEqual(c["INSS patronal"], D("600.00"))
        self.assertEqual(c["RAT"], D("60.00"))
        self.assertEqual(c["Terceiros"], D("174.00"))
        self.assertEqual(c["Prov. 13º"], D("250.00"))
        self.assertEqual(c["Prov. férias"], D("333.33"))
        g = totais_guias([h])
        self.assertEqual(g["INSS segurados (descontado)"], D("248.60"))
        self.assertEqual(g["Total DCTFWeb (previdência)"], D("1082.60"))


class TestBanco(unittest.TestCase):
    def test_ida_e_volta(self):
        with tempfile.TemporaryDirectory() as pasta:
            con = banco.conectar(Path(pasta) / "t.db")
            f = Funcionario(nome="Ana", salario=D("3000"), periculosidade=True, adiantamento_pct=D("40"))
            f.id = banco.inserir_funcionario(con, f)
            self.assertEqual(banco.obter_funcionario(con, f.id), f)

            banco.salvar_lancamento(con, f.id, "2026-09", Lancamento(horas_extras_50=D("10")))
            h = calcular_folha(f, banco.obter_lancamento(con, f.id, "2026-09"), "2026-09")
            banco.gravar_holerite(con, f.id, "2026-09", h)
            self.assertEqual(banco.ler_holerite(con, f.id, "2026-09"), h)
            variaveis = h.proventos["Horas extras 50%"] + h.proventos["DSR sobre variáveis"]
            self.assertEqual(banco.media_variaveis(con, f.id, "2026-01", "2026-12"), variaveis)
            con.close()


if __name__ == "__main__":
    unittest.main()
