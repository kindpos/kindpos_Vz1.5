import argparse
import json
import os
import sys
from typing import Dict, Any

# Ensure project root is in sys.path so 'core' can be imported
# This allows running from project root: python core/backend/app/printing/test_print.py ...
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Check if the path is correct by trying to import core
try:
    import core
except ImportError:
    # If it fails, try one level up (depends on where we are executed from)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from app.printing.templates.guest_receipt import GuestReceiptTemplate
from app.printing.templates.kitchen_ticket import KitchenTicketTemplate
from app.printing.templates.delivery_kitchen import DeliveryKitchenTicketTemplate
from app.printing.templates.driver_receipt import DriverReceiptTemplate
from app.printing.templates.char_test_template import CharacterTestTemplate
from app.printing.escpos_formatter import ESCPOSFormatter

def load_fixture(name: str) -> Dict[str, Any]:
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", f"{name}.json")
    if not os.path.exists(fixture_path):
        print(f"Error: Fixture {name} not found at {fixture_path}")
        sys.exit(1)
    with open(fixture_path, 'r') as f:
        return json.load(f)

def get_template(name: str):
    if "receipt" in name:
        return GuestReceiptTemplate()
    elif "kitchen_ticket" in name:
        return KitchenTicketTemplate()
    elif "delivery_kitchen" in name:
        return DeliveryKitchenTicketTemplate()
    elif "driver_receipt" in name:
        return DriverReceiptTemplate()
    elif "char_test" in name:
        return CharacterTestTemplate()
    else:
        # Default to GuestReceipt if unsure
        return GuestReceiptTemplate()

def main():
    parser = argparse.ArgumentParser(description="KINDpos Print Test Script")
    parser.add_argument("--fixture", required=True, help="Fixture name (e.g. receipt_dine_in)")
    parser.add_argument("--ip", required=True, help="Printer IP address")
    parser.add_argument("--width", type=int, default=80, help="Paper width (80 or 58)")
    
    args = parser.parse_args()
    
    print(f"--- KINDpos Print Test ---")
    print(f"Fixture: {args.fixture}")
    print(f"Printer IP: {args.ip}")
    print(f"Paper Width: {args.width}mm")
    
    # 1. Load Fixture
    context = load_fixture(args.fixture)
    
    # 2. Select Template
    template = get_template(args.fixture)
    template.paper_width = args.width # Match chars_per_line in template
    
    # 3. Render Template
    commands = template.render(context)
    print(f"Template rendered ({len(commands)} commands)")
    
    # 4. Format for ESC/POS
    formatter = ESCPOSFormatter(paper_width=args.width)
    raw_bytes = formatter.format(commands)
    print(f"ESC/POS formatting complete ({len(raw_bytes)} bytes)")
    
    # 5. Send to Printer
    print(f"Connecting to {args.ip}...")
    try:
        from escpos.printer import Network
        printer = Network(args.ip)
        printer._raw(raw_bytes)
        print("Success: Data sent to printer.")
    except ImportError:
        print("Error: python-escpos library not installed.")
        print("Install it with: pip install python-escpos")
    except Exception as e:
        print(f"Error sending to printer: {e}")

if __name__ == "__main__":
    main()
