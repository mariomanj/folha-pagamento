import unittest
from decimal import Decimal as D

from folha.calculo import Funcionario, Lancamento, calcular_folha, calcular_inss, calcular_irrf


class TestINSS(unittest.TestCase):
    def test_salario_minimo(self):
        self.assertEqual(calcular_inss(D("1621.00")), D("121.58"))

    def test_progressivo_segunda_faixa(self):
        # 1621 * 7,5% + (2500 - 1621) * 9%
        self.assertEqual(calcular_inss(D("2500")), D("200.69"))

    def test_teto(self):
        self.assertEqual(calcular_inss(D("20000")), calcular_inss(D("8475.55")))
        self.assertEqual(calcular_inss(D("8475.55")), D("988.09"))


class TestIRRF(unittest.TestCase):
    def test_isento_ate_5000(self):
        self.assertEqual(calcular_irrf(D("5000"), calcular_inss(D("5000"))), D("0"))

    def test_faixa_de_reducao_parcial(self):
        renda = D("6000")
        inss = calcular_inss(renda)
        cheio = (renda - inss) * D("0.275") - D("908.73")
        reducao = D("978.62") - D("0.133145") * renda
        self.assertEqual(calcular_irrf(renda, inss), (cheio - reducao).quantize(D("0.01")))

    def test_sem_reducao_acima_7350(self):
        renda = D("10000")
        inss = calcular_inss(renda)
        esperado = ((renda - inss) * D("0.275") - D("908.73")).quantize(D("0.01"))
        self.assertEqual(calcular_irrf(renda, inss), esperado)

    def test_dependentes_reduzem_imposto(self):
        renda = D("9000")
        inss = calcular_inss(renda)
        self.assertLess(calcular_irrf(renda, inss, dependentes=2), calcular_irrf(renda, inss))


class TestFolha(unittest.TestCase):
    def test_horas_extras_e_faltas(self):
        f = Funcionario(nome="Ana", salario=D("2200"))
        h = calcular_folha(f, Lancamento(horas_extras_50=D("10"), faltas_dias=D("1")))
        self.assertEqual(h.proventos["Horas extras 50%"], D("150.00"))  # 10h * 10 * 1,5
        self.assertEqual(h.descontos["Faltas"], D("73.33"))
        self.assertEqual(h.base_inss, D("2276.67"))
        self.assertEqual(h.fgts, D("182.13"))

    def test_vale_transporte_limitado_a_6_por_cento(self):
        f = Funcionario(nome="Bia", salario=D("2000"), usa_vt=True, valor_vt=D("300"))
        self.assertEqual(calcular_folha(f).descontos["Vale-transporte"], D("120.00"))
        f.valor_vt = D("80")
        self.assertEqual(calcular_folha(f).descontos["Vale-transporte"], D("80.00"))

    def test_liquido(self):
        h = calcular_folha(Funcionario(nome="Caio", salario=D("3000")))
        self.assertEqual(h.liquido, h.total_proventos - h.total_descontos)
        self.assertNotIn("IRRF", h.descontos)


if __name__ == "__main__":
    unittest.main()
