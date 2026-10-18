"""
icon_drawing.py - drawing small, smooth icons at any size in plain Python, so they are sharp at every display
scaling. A shape is a "distance function": for a point (x, y) in a square from 0 to 1 it says how far the point is
from the shape's edge (negative inside). Painting a shape fills the pixels it covers, with soft edges.

    drawing = Drawing(24)
    drawing.paint(circle(0.5, 0.5, 0.4), "#5fd38d")
    drawing.paint(segment(0.3, 0.5, 0.45, 0.65, 0.1), "#ffffff")
    png = drawing.png()
"""

import math

from litterbox.gui.logic import png_images


def rgba(color, alpha=1.0):
    """'#rrggbb' or (r, g, b) -> (r, g, b, a) with a from 0 to 1."""
    if isinstance(color, str):
        text = color.lstrip("#")
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), alpha
    return color[0], color[1], color[2], (color[3] if len(color) > 3 else 1.0) * alpha


class Drawing:
    """A square picture `size` pixels wide, transparent to start with."""

    def __init__(self, size, width=None):
        self.width, self.height = width or size, size
        self.pixels = bytearray(self.width * self.height * 4)

    def paint(self, shape, color, alpha=1.0, left=0.0):
        """Fill `shape` with `color`. `left` moves it right by that many picture heights (for wide pictures made of
        several icons side by side)."""
        r, g, b, a = rgba(color, alpha)
        size = self.height
        for y in range(self.height):
            v = (y + 0.5) / size
            for x in range(self.width):
                u = (x + 0.5) / size - left
                coverage = 0.5 - shape(u, v) * size          # distance in pixels -> how much of the pixel is inside
                if coverage <= 0:
                    continue
                coverage = min(coverage, 1.0) * a
                i = (y * self.width + x) * 4
                below = self.pixels[i + 3] / 255
                out = coverage + below * (1 - coverage)
                if out <= 0:
                    continue
                for c, value in enumerate((r, g, b)):
                    self.pixels[i + c] = round((value * coverage + self.pixels[i + c] * below * (1 - coverage)) / out)
                self.pixels[i + 3] = round(out * 255)

    def png(self):
        return png_images.encode(self.width, self.height, self.pixels)


# -- shapes ---------------------------------------------------------------------------------------------------------

def circle(cx, cy, r):
    return lambda x, y: math.hypot(x - cx, y - cy) - r


def ring(cx, cy, r, width):
    return lambda x, y: abs(math.hypot(x - cx, y - cy) - r) - width / 2


def box(cx, cy, half_w, half_h, radius=0.0):
    """A rectangle centred on (cx, cy), with rounded corners."""
    def shape(x, y):
        qx, qy = abs(x - cx) - half_w + radius, abs(y - cy) - half_h + radius
        outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
        return outside + min(max(qx, qy), 0.0) - radius
    return shape


def segment(ax, ay, bx, by, width):
    """A straight line with round ends."""
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy or 1e-9

    def shape(x, y):
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length))
        return math.hypot(x - ax - t * dx, y - ay - t * dy) - width / 2
    return shape


def polyline(points, width):
    """Lines joining the points in order."""
    return union(*[segment(*points[i], *points[i + 1], width) for i in range(len(points) - 1)])


def polygon(points):
    """A filled shape with these corners (in order, any simple polygon)."""
    count = len(points)

    def shape(x, y):
        best = math.inf
        inside = False
        for i in range(count):
            ax, ay = points[i]
            bx, by = points[i - 1]
            ex, ey = bx - ax, by - ay
            wx, wy = x - ax, y - ay
            t = max(0.0, min(1.0, (wx * ex + wy * ey) / ((ex * ex + ey * ey) or 1e-9)))
            best = min(best, math.hypot(wx - ex * t, wy - ey * t))
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / ((by - ay) or 1e-9) + ax:
                inside = not inside
        return -best if inside else best
    return shape


def regular_polygon(cx, cy, r, sides, turn=0.0):
    return polygon([(cx + r * math.cos(turn + 2 * math.pi * i / sides), cy + r * math.sin(turn + 2 * math.pi * i / sides))
                    for i in range(sides)])


def union(*shapes):
    return lambda x, y: min(shape(x, y) for shape in shapes)


def subtract(shape, cut):
    """`shape` with `cut` taken out of it."""
    return lambda x, y: max(shape(x, y), -cut(x, y))


def grow(shape, amount):
    """The shape made bigger all round (for an outline drawn behind it)."""
    return lambda x, y: shape(x, y) - amount


def placed(shape, scale, left, top):
    """A shape drawn for the whole square, shrunk to `scale` and moved to (left, top) (for small badges)."""
    return lambda x, y: shape((x - left) / scale, (y - top) / scale) * scale
