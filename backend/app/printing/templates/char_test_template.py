from typing import List, Dict, Any
from .base_template import BaseTemplate

class CharacterTestTemplate(BaseTemplate):
    """
    Dedicated character verification receipt.
    Tests various special characters, accents, and symbols.
    """

    def render(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        commands = super().render(context)
        
        # Header
        commands.append({'type': 'text', 'content': '================================', 'align': 'center'})
        commands.append({'type': 'text', 'content': context.get('restaurant_name', 'CHARACTER VERIFICATION TEST'), 'bold': True, 'align': 'center'})
        commands.append({'type': 'text', 'content': '================================', 'align': 'center'})
        commands.append({'type': 'feed', 'lines': 1})

        # Currency
        commands.append({'type': 'text', 'content': 'CURRENCY:', 'bold': True})
        cur = context.get('currency_test', {})
        commands.append({'type': 'text', 'content': f"  Dollar       {cur.get('dollar', '$1.00')}"})
        commands.append({'type': 'text', 'content': f"  Cent         {cur.get('cent', '99¢')}"})
        commands.append({'type': 'feed', 'lines': 1})

        # Accents
        commands.append({'type': 'text', 'content': 'ACCENTED CHARACTERS:', 'bold': True})
        accents = context.get('accent_test', '').split('\n')
        for line in accents:
            commands.append({'type': 'text', 'content': f"  {line}"})
        commands.append({'type': 'feed', 'lines': 1})

        # Symbols
        commands.append({'type': 'text', 'content': 'SYMBOLS:', 'bold': True})
        symbols = context.get('symbol_test', '').split('\n')
        for line in symbols:
            commands.append({'type': 'text', 'content': f"  {line}"})
        commands.append({'type': 'feed', 'lines': 1})

        # Punctuation
        commands.append({'type': 'text', 'content': 'PUNCTUATION STRESS TEST:', 'bold': True})
        punc = context.get('punctuation_test', '').split('\n')
        for line in punc:
            commands.append({'type': 'text', 'content': f"  {line}"})
        commands.append({'type': 'feed', 'lines': 1})

        # Line Formatting
        commands.append({'type': 'text', 'content': 'LINE FORMATTING:', 'bold': True})
        formatting = context.get('formatting_test', '').split('\n')
        for line in formatting:
            commands.append({'type': 'text', 'content': f"  {line}"})
        commands.append({'type': 'feed', 'lines': 1})

        # Wrap Test (Simulating Guest Receipt item style but with long name)
        commands.append({'type': 'text', 'content': 'LONG ITEM NAME WRAP TEST:', 'bold': True})
        for item in context.get('items', []):
            name = item.get('name', '')
            price = item.get('price', 0.0)
            wrapped_name = self._wrap_text(name, self.chars_per_line - 15)
            
            # First line with Qty and first part of name and price
            first_line = f"1 {wrapped_name[0]:<{self.chars_per_line-15}} ${price:>7.2f}"
            commands.append({'type': 'text', 'content': first_line, 'bold': True})
            
            # Remaining lines of name
            for line in wrapped_name[1:]:
                commands.append({'type': 'text', 'content': f"  {line}", 'bold': True})
            
            # Modifier Stress Test (Special instructions)
            spec_inst = item.get('special_instructions', '')
            if spec_inst:
                commands.append({'type': 'feed', 'lines': 1})
                commands.append({'type': 'text', 'content': 'MODIFIER STRESS TEST:', 'bold': True})
                wrapped_inst = self._wrap_text(spec_inst, self.chars_per_line - 4)
                for line in wrapped_inst:
                    commands.append({'type': 'text', 'content': f"  {line}", 'bold': True})

        # Footer
        commands.append({'type': 'feed', 'lines': 1})
        
        # Spanish Test
        span = context.get('spanish_test')
        if span:
            for line in span.get('header', '').split('\n'):
                commands.append({'type': 'text', 'content': line, 'align': 'center'})
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({'type': 'text', 'content': 'SPECIAL CHARACTERS:', 'bold': True})
            for line in span.get('special_chars', '').split('\n'):
                commands.append({'type': 'text', 'content': f"  {line}"})
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({'type': 'text', 'content': 'SAMPLE MENU ITEMS:', 'bold': True})
            for line in span.get('menu_items', []):
                commands.append({'type': 'text', 'content': f"  {line}"})
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({'type': 'text', 'content': 'SAMPLE RECEIPT TEXT:', 'bold': True})
            for line in span.get('receipt_text', '').split('\n'):
                commands.append({'type': 'text', 'content': f"  {line}"})
            commands.append({'type': 'feed', 'lines': 1})

        # Italian Test
        ital = context.get('italian_test')
        if ital:
            for line in ital.get('header', '').split('\n'):
                commands.append({'type': 'text', 'content': line, 'align': 'center'})
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({'type': 'text', 'content': 'SPECIAL CHARACTERS:', 'bold': True})
            for line in ital.get('special_chars', '').split('\n'):
                commands.append({'type': 'text', 'content': f"  {line}"})
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({'type': 'text', 'content': 'SAMPLE MENU ITEMS:', 'bold': True})
            for line in ital.get('menu_items', []):
                commands.append({'type': 'text', 'content': f"  {line}"})
            commands.append({'type': 'feed', 'lines': 1})
            commands.append({'type': 'text', 'content': 'SAMPLE RECEIPT TEXT:', 'bold': True})
            for line in ital.get('receipt_text', '').split('\n'):
                commands.append({'type': 'text', 'content': f"  {line}"})
            commands.append({'type': 'feed', 'lines': 1})

        commands.append({'type': 'text', 'content': '================================', 'align': 'center'})
        footer = context.get('footer_message', '').split('\n')
        for line in footer:
            commands.append({'type': 'text', 'content': f"   {line}", 'bold': True, 'align': 'center'})
        commands.append({'type': 'text', 'content': '================================', 'align': 'center'})
        
        commands.append({'type': 'feed', 'lines': 3})
        commands.append({'type': 'cut', 'partial': False})
        return commands
