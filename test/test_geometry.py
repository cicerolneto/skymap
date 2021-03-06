import unittest
from skymap.geometry import *


class RectangleTest(unittest.TestCase):
    def test_center(self):
        r = Rectangle(Point(1, 2), Point(5, 3))
        self.assertEqual(r.center, Point(3, 2.5))

    def test_overlap(self):
        r1 = Rectangle(Point(0, 0), Point(1,1))
        r2 = Rectangle(Point(0.5, 0), Point(1.5, 1))
        self.assertEqual(r1.overlap(r2), 0.5)

        c1 = Circle(Point(1, 0.5), 0.5)
        self.assertEqual(r1.overlap(c1), 0.5)

        c2 = Circle(Point(4, 0), 0.5)
        self.assertEqual(r1.overlap(c2), 0)

        r3 = Rectangle(Point(-44.1658022222, 1.05834038889), Point(44.1658022222, 4.97850936111))
        c3 = Circle(Point(-1, 0), 0.5)
        c4 = Circle(Point(1, 0), 0.5)
        c5 = Circle(Point(1, 1), 0.5)

        self.assertEqual(r3.overlap(c3), 0)
        self.assertEqual(r3.overlap(c4), 0)
        self.assertEqual(r3.overlap(c5), 0.44165961110999996)