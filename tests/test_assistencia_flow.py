import unittest
from modules.suporte.blueprints.assistencia import STATUS_DEPT_OWNERS, JOURNEY_STEPS


class AssistenciaFlowTest(unittest.TestCase):
    def test_estoque_has_access_to_concluido(self):
        # Verify ESTOQUE is in the STATUS_DEPT_OWNERS for 'concluído' status
        owners = STATUS_DEPT_OWNERS.get("concluído")
        self.assertIsNotNone(owners)
        self.assertIn("ESTOQUE", owners)

    def test_estoque_listed_in_journey_steps_concluido(self):
        # Verify 'Estoque' is listed in JOURNEY_STEPS for 'concluído'
        concluido_step = next((step for step in JOURNEY_STEPS if step["key"] == "concluído"), None)
        self.assertIsNotNone(concluido_step)
        self.assertIn("Estoque", concluido_step["owners"])


if __name__ == "__main__":
    unittest.main()
