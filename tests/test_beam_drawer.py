from __future__ import annotations

import unittest

from ui.drawers.beam_drawer import BeamDrawer


class BeamDrawerTests(unittest.TestCase):
    def test_rounded_polygon_leaves_zero_radius_beams_unchanged(self) -> None:
        polygon = ((0.0, 0.0), (0.0, 8.0), (2.0, 8.0), (2.0, 0.0))

        self.assertEqual(BeamDrawer._rounded_polygon(polygon, 0.0), polygon)

    def test_rounded_polygon_replaces_beam_corners_with_arcs(self) -> None:
        polygon = ((0.0, 0.0), (0.0, 8.0), (2.0, 8.0), (2.0, 0.0))

        rounded = BeamDrawer._rounded_polygon(polygon, 0.5)

        self.assertEqual(len(rounded), 68)
        self.assertNotIn(polygon[0], rounded)
        self.assertAlmostEqual(rounded[0][0], 0.5)
        self.assertAlmostEqual(rounded[0][1], 0.0)


if __name__ == "__main__":
    unittest.main()