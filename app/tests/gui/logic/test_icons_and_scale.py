"""Tests for gui/logic/png_images.py, icon_drawing.py, status_icons.py and ui_scale.py: the icons Litterbox draws,
and sizes that follow the display."""

import unittest
from pathlib import Path

from litterbox.gui.logic import icon_drawing
from litterbox.gui.logic import png_images
from litterbox.gui.logic import status_icons
from litterbox.gui.logic import ui_scale

ASSETS = Path(__file__).resolve().parents[3] / "litterbox" / "gui" / "assets"


class Png(unittest.TestCase):
    def test_encode_then_decode_gives_the_same_pixels(self):
        pixels = bytearray(range(256)) * 3 + bytearray(range(0, 256, 4))       # 4 x 52 RGBA
        width, height = 4, len(pixels) // 16
        decoded = png_images.decode(png_images.encode(width, height, pixels))
        self.assertEqual(decoded, (width, height, pixels))

    def test_not_a_png(self):
        self.assertIsNone(png_images.decode(b"GIF89a"))

    def test_resize_averages_and_ignores_transparent_colour(self):
        pixels = bytearray([255, 0, 0, 255, 0, 0, 255, 0] * 2)            # red, and a transparent blue, twice
        out = png_images.resize(2, 2, pixels, 1, 1)
        self.assertEqual(tuple(out), (255, 0, 0, 127))

    def test_the_litterbox_icon_can_be_read_and_shrunk(self):
        for name in ("litterbox_icon_white.ico", "litterbox_icon_black.ico"):
            picture = png_images.ico_png((ASSETS / name).read_bytes())
            width, height, pixels = png_images.decode(picture)
            new_width, new_height, small = png_images.fit_height(width, height, pixels, 20)
            self.assertEqual(new_height, 20)
            self.assertEqual(len(small), new_width * 20 * 4)
            self.assertTrue(any(small[3::4]))                 # something is visible

    def test_ico_without_png(self):
        self.assertIsNone(png_images.ico_png(b"\x00\x00\x01\x00\x00\x00"))
        self.assertIsNone(png_images.ico_png(b""))


class Drawing(unittest.TestCase):
    def alpha(self, picture, x, y):
        return picture.pixels[(y * picture.width + x) * 4 + 3]

    def test_a_circle_covers_its_middle_and_not_its_corners(self):
        picture = icon_drawing.Drawing(20)
        picture.paint(icon_drawing.circle(0.5, 0.5, 0.4), "#ff0000")
        self.assertEqual(self.alpha(picture, 10, 10), 255)
        self.assertEqual(self.alpha(picture, 0, 0), 0)
        self.assertEqual(picture.pixels[(10 * 20 + 10) * 4:(10 * 20 + 10) * 4 + 3], bytearray([255, 0, 0]))

    def test_edges_are_soft(self):
        picture = icon_drawing.Drawing(20)
        picture.paint(icon_drawing.circle(0.5, 0.5, 0.4), "#ffffff")
        edge = [self.alpha(picture, x, 10) for x in range(20)]
        self.assertTrue(any(0 < value < 255 for value in edge))

    def test_subtract_makes_a_hole(self):
        picture = icon_drawing.Drawing(20)
        picture.paint(icon_drawing.subtract(icon_drawing.circle(0.5, 0.5, 0.45), icon_drawing.circle(0.5, 0.5, 0.2)),
                      "#ffffff")
        self.assertEqual(self.alpha(picture, 10, 10), 0)
        self.assertEqual(self.alpha(picture, 10, 3), 255)

    def test_polygon_inside_and_outside(self):
        triangle = icon_drawing.polygon([(0.5, 0.1), (0.9, 0.9), (0.1, 0.9)])
        self.assertLess(triangle(0.5, 0.6), 0)
        self.assertGreater(triangle(0.1, 0.1), 0)


class StatusIcons(unittest.TestCase):
    COLORS = {"box": "#949a9f", "accent": "#1f6aa5", "busy": "#d9a520", "cloud": "#9ecbff", "ok": "#e6e6e6"}

    def test_every_shape_draws_at_every_size(self):
        for name in status_icons.SHAPES:
            for size in (12, 24, 41):
                width, height, _pixels = png_images.decode(status_icons.icon_png(name, size, "#ffffff"))
                self.assertEqual((width, height), (size, size), name)

    def test_every_status_has_its_own_shape_or_shares_one_meaning(self):
        shapes = {}
        for kind, (shape, _title, _text) in status_icons.STATUS.items():
            shapes.setdefault(shape, set()).add(kind)
        for shape, kinds in shapes.items():
            self.assertTrue(kinds <= {"unclaimed", "stray"} or kinds <= {"missing", "error"} or len(kinds) == 1, kinds)

    def test_row_strip_is_tick_then_icon(self):
        for ticked in (False, True):
            data = status_icons.row_strip_png(24, ticked, "ok", self.COLORS, busy=True, not_downloaded=True)
            width, height, pixels = png_images.decode(data)
            self.assertEqual((width, height), (status_icons.strip_width(24), 24))
        unknown = status_icons.row_strip_png(24, False, "something new", self.COLORS)
        self.assertTrue(unknown.startswith(png_images.PNG_SIGNATURE))

    def test_legend_and_labels(self):
        titles = [title for _shape, title, _text in status_icons.legend()]
        self.assertIn("Checked out by you", titles)
        self.assertIn("Not downloaded", titles)
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(status_icons.status_label("released"), "Released")
        self.assertEqual(status_icons.status_label("???"), "Unreadable")


class Scale(unittest.TestCase):
    def test_text_size_setting(self):
        self.assertEqual(ui_scale.text_size({}), 100)
        self.assertEqual(ui_scale.text_size({"text_size": 115}), 115)
        self.assertEqual(ui_scale.text_size({"text_size": "130%"}), 130)
        self.assertEqual(ui_scale.text_size({"text_size": 117}), 100)
        self.assertEqual(ui_scale.text_size({"text_size": "big"}), 100)
        self.assertEqual(ui_scale.text_size(None), 100)

    def test_stepping(self):
        self.assertEqual(ui_scale.step(100, 1), 115)
        self.assertEqual(ui_scale.step(130, 1), 130)
        self.assertEqual(ui_scale.step(90, -1), 90)
        self.assertEqual(ui_scale.step(130, 0), 100)
        self.assertEqual(ui_scale.step(77, 1), 115)

    def test_pixels_follow_the_scale(self):
        self.assertEqual(ui_scale.px(26, 1.5), 39)
        self.assertEqual(ui_scale.px(0, 2), 1)
        self.assertEqual(ui_scale.font_px(14, 1.5), -21)
        self.assertEqual(ui_scale.font_px(10, 1.0), -ui_scale.SMALL_FONT)     # never below the smallest size

    def test_sidebar_collapses_on_narrow_windows(self):
        self.assertTrue(ui_scale.sidebar_collapsed(1500, 1.5))               # 1000 at 100%
        self.assertFalse(ui_scale.sidebar_collapsed(1920, 1.5))


if __name__ == "__main__":
    unittest.main()
