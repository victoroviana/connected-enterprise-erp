import unittest

from forms import cnpj_valido


class TestCNPJValido(unittest.TestCase):

    def test_cnpj_valido_retorna_true_para_numero_valido(self):
        self.assertTrue(cnpj_valido("04.252.011/0001-10"))

    def test_cnpj_valido_retorna_false_para_digitos_repetidos(self):
        self.assertFalse(cnpj_valido("11.111.111/1111-11"))

    def test_cnpj_valido_retorna_false_para_digitos_verificadores_invalidos(self):
        self.assertFalse(cnpj_valido("04.252.011/0001-11"))


if __name__ == "__main__":
    unittest.main()
