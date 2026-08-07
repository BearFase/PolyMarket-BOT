import unittest
from pathlib import Path


class PositionChartTests(unittest.TestCase):
    def test_event_history_is_not_rendered_as_position_history(self):
        html = Path("dashboard_live.html").read_text(encoding="utf-8")
        self.assertNotIn("history[p.event_slug]", html)
        self.assertNotIn("fetch('price_history.json", html)
        self.assertIn("p.current_price", html)
        self.assertIn("p.entry_price", html)


if __name__ == "__main__":
    unittest.main()
