import os
import re

def fix_test_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add pytest import if missing and we are adding decorators
    if 'import pytest' not in content:
        content = 'import pytest\n' + content

    # Find async def test_* functions that don't have @pytest.mark.asyncio
    pattern = r'(?<!@pytest\.mark\.asyncio\n)\s*async def test_\w+'
    
    def add_decorator(match):
        func_def = match.group(0)
        # Check if it already has the decorator (regex negative lookbehind is a bit tricky with whitespace)
        if '@pytest.mark.asyncio' in content[max(0, match.start()-50):match.start()]:
            return func_def
        
        # Get indentation
        indent = re.match(r'^\s*', func_def).group(0)
        return f'\n{indent}@pytest.mark.asyncio{func_def}'

    new_content = re.sub(r'(\s*)async def test_', r'\1@pytest.mark.asyncio\1async def test_', content)
    
    # Avoid duplicate decorators if they already existed
    new_content = new_content.replace('@pytest.mark.asyncio\n@pytest.mark.asyncio', '@pytest.mark.asyncio')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)

test_files = [
    r'C:\Users\bgkd2\PycharmProjects\KINDpos_vz0.9\backend\tests\test_event_ledger.py',
    r'C:\Users\bgkd2\PycharmProjects\KINDpos_vz0.9\backend\tests\test_printer_system.py'
]

for f in test_files:
    if os.path.exists(f):
        print(f"Fixing {f}")
        fix_test_file(f)
    else:
        print(f"File not found: {f}")
