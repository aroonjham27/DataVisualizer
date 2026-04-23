from __future__ import annotations

import unittest
from pathlib import Path

from datavisualizer.semantic_model import load_semantic_model


MODEL_PATH = Path(__file__).resolve().parents[1] / "configs" / "semantic_models" / "pilot_pricing_v0.json"


class SemanticModelTests(unittest.TestCase):
    def test_loads_pilot_semantic_model(self) -> None:
        model = load_semantic_model(MODEL_PATH)

        self.assertEqual(model.name, "pilot_pricing_v0")
        self.assertEqual(model.version, "v0")
        self.assertIn("opportunities", model.entities)
        self.assertIn("usage_metrics", model.entities)
        self.assertGreater(len(model.allowed_joins), 0)


if __name__ == "__main__":
    unittest.main()
