"""
KINDpos Logo Utility — ESC/POS bitmap conversion

Converts a B&W PNG logo to ESC/POS GS v 0 bitmap bytes.
Method: sharpen x2 -> contrast boost -> grayscale -> Floyd-Steinberg dither
Centered on full paper canvas before encoding.

Returns raw bytes for storage in VENUE config block.
Pillow required only at onboarding time, not at runtime.

Usage:
    from backend.app.printing.logo_utils import logo_to_escpos_bytes

    VENUE = {
        'logo_bytes': logo_to_escpos_bytes('sammys-logo-bw.png', target_width=250),
        ...
    }
"""

import struct


def logo_to_escpos_bytes(
    img_path: str,
    target_width: int = 150,
    paper_width_px: int = 576,
    sharpen_passes: int = 2,
    contrast: float = 3.0,
) -> bytes:
    """
    Converts a B&W PNG logo to ESC/POS GS v 0 bitmap bytes.

    Args:
        img_path: Path to the source PNG image.
        target_width: Desired logo width in pixels (scaled proportionally).
        paper_width_px: Total paper width in pixels (576 for 80mm @ 203dpi).
        sharpen_passes: Number of sharpen filter passes (default 2).
        contrast: Contrast enhancement factor (default 3.0).

    Returns:
        Raw bytes suitable for sending directly to an ESC/POS printer.
        Store in VENUE['logo_bytes'] for runtime use.
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        raise ImportError(
            "Pillow is required for logo conversion. "
            "Install with: pip install Pillow"
        )

    img = Image.open(img_path)

    # Scale proportionally to target_width
    aspect = img.height / img.width
    new_width = target_width
    new_height = int(new_width * aspect)
    img = img.resize((new_width, new_height), Image.LANCZOS)

    # Sharpen
    for _ in range(sharpen_passes):
        img = img.filter(ImageFilter.SHARPEN)

    # Contrast boost
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(contrast)

    # Convert to grayscale then 1-bit with Floyd-Steinberg dithering
    img = img.convert('L')
    img = img.convert('1')

    # Center on full paper-width canvas
    canvas = Image.new('1', (paper_width_px, new_height), 1)  # 1 = white
    x_offset = (paper_width_px - new_width) // 2
    canvas.paste(img, (x_offset, 0))

    # Encode as GS v 0 raster bitmap
    return _encode_gs_v_0(canvas)


def _encode_gs_v_0(img) -> bytes:
    """
    Encode a 1-bit PIL Image as ESC/POS GS v 0 raster bitmap.

    GS v 0 format:
        1D 76 30 00 xL xH yL yH [data]
    Where:
        xL xH = bytes per line (width_px / 8) as little-endian uint16
        yL yH = number of lines as little-endian uint16
        data  = packed 1bpp bitmap (0 = white, 1 = black, MSB first)
    """
    width = img.width
    height = img.height
    bytes_per_line = (width + 7) // 8

    # Pack header
    header = b'\x1d\x76\x30\x00'
    header += struct.pack('<HH', bytes_per_line, height)

    # Pack pixel data — 1 bit per pixel, MSB first, 0=white 1=black
    # PIL '1' mode: 0=black, 255=white — we need to invert
    pixels = img.load()
    data = bytearray()
    for y in range(height):
        for x_byte in range(bytes_per_line):
            byte_val = 0
            for bit in range(8):
                x = x_byte * 8 + bit
                if x < width:
                    pixel = pixels[x, y]
                    # PIL '1' mode: 0 = black, 255 = white
                    # ESC/POS: 1 = black dot, 0 = white
                    if pixel == 0:
                        byte_val |= (0x80 >> bit)
            data.append(byte_val)

    return header + bytes(data)
