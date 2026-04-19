"""
Tests for the ESCPOSFormatter — translates template commands into raw ESC/POS bytes.
"""

import pytest
from app.printing.escpos_formatter import (
    ESCPOSFormatter,
    INIT,
    ALIGN_LEFT,
    ALIGN_CENTER,
    ALIGN_RIGHT,
    CUT_FULL,
    CUT_PARTIAL,
    LF,
    COLOR_RED,
    COLOR_BLACK,
    REVERSE_ON,
    REVERSE_OFF,
    ESC,
    GS,
)


@pytest.fixture
def fmt():
    return ESCPOSFormatter(paper_width=80)


class TestESCPOSFormatter:

    def test_empty_commands(self, fmt):
        result = fmt.format([])
        assert result == INIT

    def test_text_basic(self, fmt):
        result = fmt.format([{'type': 'text', 'content': 'Hello'}])
        assert b'Hello' in result
        assert LF in result

    def test_text_bold(self, fmt):
        result = fmt.format([{'type': 'text', 'content': 'Bold', 'bold': True}])
        assert b'Bold' in result
        # Find the ESC ! n byte — bold sets bit 3 (0x08)
        # ESC ! is ESC + 0x21 + n
        esc_bang = ESC + b'\x21'
        idx = result.index(esc_bang)
        mode_byte = result[idx + 2]
        assert mode_byte & 0x08 == 0x08

    def test_text_center_aligned(self, fmt):
        result = fmt.format([{'type': 'text', 'content': 'Center', 'align': 'center'}])
        assert ALIGN_CENTER in result

    def test_text_right_aligned(self, fmt):
        result = fmt.format([{'type': 'text', 'content': 'Right', 'align': 'right'}])
        assert ALIGN_RIGHT in result

    def test_text_double_width_height(self, fmt):
        result = fmt.format([{
            'type': 'text', 'content': 'Big',
            'double_width': True, 'double_height': True,
        }])
        esc_bang = ESC + b'\x21'
        idx = result.index(esc_bang)
        mode_byte = result[idx + 2]
        # Double height = 0x10, double width = 0x20 → 0x30
        assert mode_byte & 0x30 == 0x30

    def test_text_red(self, fmt):
        result = fmt.format([{'type': 'text', 'content': 'Red', 'red': True}])
        text_start = result.index(b'Red')
        # COLOR_RED should appear before the text
        assert COLOR_RED in result[:text_start]
        # COLOR_BLACK should appear after the text
        assert COLOR_BLACK in result[text_start:]

    def test_text_reverse(self, fmt):
        result = fmt.format([{'type': 'text', 'content': 'Rev', 'reverse': True}])
        text_start = result.index(b'Rev')
        assert REVERSE_ON in result[:text_start]
        assert REVERSE_OFF in result[text_start:]

    def test_text_font_b(self, fmt):
        result = fmt.format([{'type': 'text', 'content': 'Small', 'font': 'b'}])
        esc_bang = ESC + b'\x21'
        idx = result.index(esc_bang)
        mode_byte = result[idx + 2]
        # Font B = bit 0 (0x01)
        assert mode_byte & 0x01 == 0x01

    def test_feed(self, fmt):
        result = fmt.format([{'type': 'feed', 'lines': 3}])
        # Should contain 3 consecutive LF bytes (after INIT)
        after_init = result[len(INIT):]
        assert after_init == LF * 3

    def test_divider(self, fmt):
        result = fmt.format([{'type': 'divider', 'char': '='}])
        # Default 80mm → 33 chars per line (Font A standard)
        assert b'=' * 33 in result
        # Must NOT contain 43+ consecutive '=' signs
        assert b'=' * 43 not in result

    def test_divider_resets_print_mode(self, fmt):
        """Divider must reset print mode before emitting chars to prevent double-width leakage."""
        result = fmt.format([{'type': 'divider', 'char': '-'}])
        divider_bytes = fmt._safe_encode('-' * 33)
        idx = result.index(divider_bytes)
        # ESC ! 0x00 (normal mode reset) should appear before the divider chars
        mode_reset = ESC + b'\x21\x00'
        preceding = result[:idx]
        assert mode_reset in preceding

    def test_cut_full(self, fmt):
        result = fmt.format([{'type': 'cut'}])
        assert CUT_FULL in result

    def test_cut_partial(self, fmt):
        result = fmt.format([{'type': 'cut', 'partial': True}])
        assert CUT_PARTIAL in result

    def test_safe_encode_unicode(self, fmt):
        result = fmt.format([{'type': 'text', 'content': 'dash\u2014here'}])
        # Em-dash should be replaced with hyphen
        assert b'dash-here' in result

    def test_paper_width_58mm(self):
        fmt58 = ESCPOSFormatter(paper_width=58)
        assert fmt58.chars_per_line == 33

        result = fmt58.format([{'type': 'divider', 'char': '-'}])
        assert b'-' * 33 in result
        # Should NOT have 48 dashes
        assert b'-' * 48 not in result
