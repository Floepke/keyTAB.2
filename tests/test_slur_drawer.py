from __future__ import annotations

import unittest
from unittest.mock import Mock

from ui.drawers.slur_drawer import SlurDrawer


class SlurDrawerTests(unittest.TestCase):
    def test_draws_tapered_cubic_curve_segments(self) -> None:
        context = Mock()
        drawer = SlurDrawer(context, (0.0, 0.0, 0.0))

        drawer.draw(((0.0, 0.0), (0.0, 8.0), (8.0, 8.0), (8.0, 0.0)), 0.5, 2.0, segment_count=100)

        self.assertEqual(context.line_to.call_count, 100)
        self.assertEqual(context.stroke.call_count, 100)
        self.assertIn(unittest.mock.call(0.5), context.set_line_width.call_args_list)
        self.assertIn(unittest.mock.call(2.0), context.set_line_width.call_args_list)


if __name__ == "__main__":
    unittest.main()