import logging
from typing import Dict, Any, List

logger = logging.getLogger("kindpos.printing.escpos_formatter")

# ── Raw ESC/POS byte constants ─────────────────────────────────────────
ESC = b'\x1b'
GS  = b'\x1d'

INIT            = ESC + b'\x40'           # ESC @ — initialize printer
ALIGN_LEFT      = ESC + b'\x61\x00'       # ESC a 0
ALIGN_CENTER    = ESC + b'\x61\x01'       # ESC a 1
ALIGN_RIGHT     = ESC + b'\x61\x02'       # ESC a 2
REVERSE_ON      = GS  + b'\x42\x01'       # GS B 1
REVERSE_OFF     = GS  + b'\x42\x00'       # GS B 0
COLOR_RED       = ESC + b'\x72\x01'       # ESC r 1
COLOR_BLACK     = ESC + b'\x72\x00'       # ESC r 0
CUT_FULL        = GS  + b'\x56\x00'       # GS V 0
CUT_PARTIAL     = GS  + b'\x56\x01'       # GS V 1
LF              = b'\x0a'                 # Line feed

# ── ESC ! n — Print mode select (PROVEN on KINDpos hardware) ──────────
#
# Single byte packs ALL formatting:
#   Bit 0: Font B       (0x01)
#   Bit 3: Bold         (0x08)
#   Bit 4: Double height(0x10)
#   Bit 5: Double width (0x20)
#
# Examples:
#   0x00 = normal font A
#   0x08 = bold
#   0x30 = double width + double height
#   0x38 = double width + double height + bold
#   0x01 = font B (small)
#   0x09 = font B + bold

# ── Unicode → ASCII replacements for thermal printers ──────────────────
CHAR_REPLACEMENTS = {
    '\u2014': '-',    # em-dash → hyphen
    '\u2013': '-',    # en-dash → hyphen
    '\u2018': "'",    # left single quote
    '\u2019': "'",    # right single quote
    '\u201c': '"',    # left double quote
    '\u201d': '"',    # right double quote
    '\u2026': '...',  # ellipsis
    '\u00a0': ' ',    # non-breaking space
}


class ESCPOSFormatter:
    """
    Translates template commands into raw ESC/POS printer bytes.
    Uses ESC ! (print mode select) for size control — verified working
    on KINDpos kitchen and receipt printers.

    Supported command types:
      text     - content, bold, double_width, double_height, align, red, reverse, font
      feed     - lines
      divider  - char
      cut      - partial
    """

    def __init__(self, paper_width: int = 80, chars_per_line: int = None):
        self.paper_width = paper_width
        if chars_per_line is not None:
            self.chars_per_line = chars_per_line
        else:
            self.chars_per_line = 42 if paper_width == 80 else 33

    def _safe_encode(self, text: str) -> bytes:
        """Encode text to bytes, replacing Unicode characters the printer can't handle."""
        for char, replacement in CHAR_REPLACEMENTS.items():
            text = text.replace(char, replacement)
        return text.encode('ascii', errors='replace')

    def _print_mode_byte(
        self,
        bold: bool = False,
        double_width: bool = False,
        double_height: bool = False,
        font_b: bool = False,
    ) -> bytes:
        """
        Build ESC ! n command.
        Single byte controls font, bold, width, and height simultaneously.
        """
        n = 0x00
        if font_b:
            n |= 0x01
        if bold:
            n |= 0x08
        if double_height:
            n |= 0x10
        if double_width:
            n |= 0x20
        return ESC + b'\x21' + bytes([n])

    def _align_cmd(self, align: str) -> bytes:
        """Build ESC a alignment command."""
        if align == 'center':
            return ALIGN_CENTER
        elif align == 'right':
            return ALIGN_RIGHT
        return ALIGN_LEFT

    def format(self, commands: List[Dict[str, Any]]) -> bytes:
        """Process formatting commands and return raw ESC/POS bytes."""
        out = bytearray()

        # Initialize printer — resets all settings, eliminates top margin
        out += INIT

        for cmd in commands:
            cmd_type = cmd.get('type')

            if cmd_type == 'text':
                content = cmd.get('content', '')
                bold = cmd.get('bold', False)
                double_width = cmd.get('double_width', False)
                double_height = cmd.get('double_height', False)
                align = cmd.get('align', 'left')
                red = cmd.get('red', False)
                reverse = cmd.get('reverse', False)
                font = cmd.get('font', 'a')

                # Set alignment
                out += self._align_cmd(align)

                # Set print mode (size + bold + font in one command)
                out += self._print_mode_byte(
                    bold=bold,
                    double_width=double_width,
                    double_height=double_height,
                    font_b=(font == 'b'),
                )

                # Optional: color and reverse
                if red:
                    out += COLOR_RED
                if reverse:
                    out += REVERSE_ON

                # Print text
                out += self._safe_encode(content)
                out += LF

                # Reset reverse and color
                if reverse:
                    out += REVERSE_OFF
                if red:
                    out += COLOR_BLACK

                # Reset print mode to normal
                out += self._print_mode_byte()
                out += ALIGN_LEFT

            elif cmd_type == 'feed':
                lines = cmd.get('lines', 1)
                out += LF * lines

            elif cmd_type == 'divider':
                char = cmd.get('char', '-')
                # Reset print mode before divider to prevent double-width leakage
                out += self._print_mode_byte()
                out += ALIGN_LEFT
                out += self._safe_encode(char * self.chars_per_line)
                out += LF

            elif cmd_type == 'logo':
                # Pre-baked GS v 0 bitmap bytes from logo_utils.logo_to_escpos_bytes()
                data = cmd.get('data', b'')
                if data:
                    out += ALIGN_CENTER
                    out += data
                    out += LF
                    out += ALIGN_LEFT

            elif cmd_type == 'cut':
                partial = cmd.get('partial', False)
                out += CUT_PARTIAL if partial else CUT_FULL

        return bytes(out)