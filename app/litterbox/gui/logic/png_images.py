"""
png_images.py - small PNG pictures made and read in plain Python: writing RGBA pixels as a PNG (for the icons
Litterbox draws itself), reading the PNG inside the Litterbox .ico, and shrinking a picture smoothly. Tk can show
PNG data directly, so no imaging library is needed.

Pixels are a bytearray of width * height * 4 bytes: red, green, blue, alpha, row by row from the top.
"""

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def encode(width, height, pixels):
    """RGBA pixels -> the bytes of a PNG file."""
    stride = width * 4
    raw = b"".join(b"\x00" + bytes(pixels[y * stride:(y + 1) * stride]) for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)      # 8 bits, RGBA, no interlace
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode(data):
    """The bytes of a PNG file -> (width, height, RGBA pixels), or None for a kind this doesn't read (only 8-bit
    RGB or RGBA without interlacing, which is what icon tools write)."""
    if not data.startswith(PNG_SIGNATURE):
        return None
    pos, header, idat = len(PNG_SIGNATURE), None, []
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + length
    if header is None:
        return None
    width, height, depth, color, _compression, _filter, interlace = header
    if depth != 8 or color not in (2, 6) or interlace:
        return None
    channels = 4 if color == 6 else 3
    stride = width * channels
    raw = zlib.decompress(b"".join(idat))
    rows, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if kind == 1:
                line[i] = (line[i] + left) & 0xFF
            elif kind == 2:
                line[i] = (line[i] + up) & 0xFF
            elif kind == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
            elif kind == 4:
                line[i] = (line[i] + _paeth(left, up, corner)) & 0xFF
        rows.append(line)
        previous = line
    if channels == 4:
        return width, height, bytearray(b"".join(rows))
    pixels = bytearray()
    for line in rows:
        for i in range(0, stride, 3):
            pixels += line[i:i + 3] + b"\xff"
    return width, height, pixels


def resize(width, height, pixels, new_width, new_height):
    """Shrink (or grow) a picture by averaging the source pixels under each new one, weighted by alpha, so edges
    stay smooth and transparent areas don't darken the colours."""
    out = bytearray(new_width * new_height * 4)
    sx, sy = width / new_width, height / new_height
    for y in range(new_height):
        y0, y1 = int(y * sy), max(int((y + 1) * sy), int(y * sy) + 1)
        for x in range(new_width):
            x0, x1 = int(x * sx), max(int((x + 1) * sx), int(x * sx) + 1)
            r = g = b = a = 0
            count = 0
            for yy in range(y0, min(y1, height)):
                base = yy * width * 4
                for xx in range(x0, min(x1, width)):
                    i = base + xx * 4
                    alpha = pixels[i + 3]
                    r += pixels[i] * alpha
                    g += pixels[i + 1] * alpha
                    b += pixels[i + 2] * alpha
                    a += alpha
                    count += 1
            o = (y * new_width + x) * 4
            if a:
                out[o:o + 4] = bytes((r // a, g // a, b // a, a // max(count, 1)))
    return out


def ico_png(data):
    """The largest PNG picture inside a Windows .ico file's bytes, or None."""
    if len(data) < 6:
        return None
    _reserved, kind, count = struct.unpack("<HHH", data[:6])
    best = None
    for i in range(count):
        entry = data[6 + 16 * i:22 + 16 * i]
        if len(entry) < 16:
            break
        width, _h, _colors, _r, _planes, _bits, size, offset = struct.unpack("<BBBBHHII", entry)
        picture = data[offset:offset + size]
        if picture.startswith(PNG_SIGNATURE) and (best is None or (width or 256) > best[0]):
            best = (width or 256, picture)
    return best[1] if best else None


def fit_height(width, height, pixels, new_height):
    """Resize a picture to a height, keeping its shape."""
    new_width = max(1, round(width * new_height / height))
    return new_width, new_height, resize(width, height, pixels, new_width, new_height)
