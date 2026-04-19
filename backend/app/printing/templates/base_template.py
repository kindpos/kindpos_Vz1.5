import logging
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger("kindpos.printing.templates")

class BaseTemplate:
    """
    Base class for all print templates.
    Provides shared building blocks for rendering.
    """

    def __init__(self, paper_width: int = 80, chars_per_line: int = None):
        self.paper_width = paper_width
        if chars_per_line is not None:
            self.chars_per_line = chars_per_line
        else:
            self.chars_per_line = 42 if paper_width == 80 else 33

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Produce a list of formatting commands for the ESC/POS formatter.
        Each command is a dict like {'type': 'text', 'content': '...', 'bold': True}
        """
        commands = []
        
        # 1. Reprint Marker (Spec 1.5)
        if context.get('is_reprint'):
            commands.extend(self._render_reprint_header(context))
            
        return commands

    def _render_reprint_header(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        fired_at = context.get('original_fired_at') or context.get('original_printed_at') or "Unknown"
        # Format if it looks like ISO
        if isinstance(fired_at, str) and "T" in fired_at:
            try:
                # Try to parse and format nicely
                dt = datetime.fromisoformat(fired_at.replace('Z', '+00:00'))
                fired_at = dt.strftime("%I:%M %p")
            except:
                pass
        return [
            {'type': 'text', 'content': '** REPRINT **', 'bold': True, 'align': 'center'},
            {'type': 'text', 'content': f'Originally fired: {fired_at}', 'align': 'center'},
            {'type': 'feed', 'lines': 1}
        ]

    def _format_time(self, timestamp: Any) -> str:
        """Helper to format ISO timestamp to HH:MM AM/PM."""
        if not timestamp or timestamp == 'N/A':
            return 'N/A'
        if isinstance(timestamp, str) and "T" in timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                return dt.strftime("%I:%M %p")
            except:
                return str(timestamp)
        return str(timestamp)

    def _format_datetime(self, timestamp: Any) -> str:
        """Helper to format ISO timestamp to MM/DD/YYYY HH:MM AM/PM."""
        if not timestamp or timestamp == 'N/A':
            return 'N/A'
        if isinstance(timestamp, str) and "T" in timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                return dt.strftime("%m/%d/%Y %I:%M %p")
            except:
                return str(timestamp)
        return str(timestamp)

    def _wrap_text(self, text: str, width: int) -> List[str]:
        """Wrap text at word boundaries."""
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            if current_length + len(word) + 1 <= width:
                current_line.append(word)
                current_length += len(word) + 1
            else:
                lines.append(" ".join(current_line))
                current_line = [word]
                current_length = len(word)
        
        if current_line:
            lines.append(" ".join(current_line))
            
        return lines
