from enum import Enum
from typing import Optional, List
from pydantic import BaseModel
from ..core.events import OrderType

class StationType(str, Enum):
    HOT_LINE   = 'hot_line'
    COLD_LINE  = 'cold_line'
    BAR        = 'bar'
    DESSERT    = 'dessert'
    EXPO       = 'expo'
    RECEIPT    = 'receipt'
    DELIVERY   = 'delivery'
    GENERAL    = 'general'   # catch-all for simple setups

class PrinterStation(BaseModel):
    mac_address:   str    # identity anchor — immutable
    nickname:      str    # 'Hot Line', 'Bar', 'Front Receipt'
    station_type:  StationType
    ip_address:    str    # resolved at print time, not stored as truth
    paper_width:   int    # 80 or 58 (mm)
    is_active:     bool = True

class PrintRoutingRule(BaseModel):
    station_mac:       str           # FK to PrinterStation
    order_types:       List[OrderType]
    template_id:       str           # which template to use
    category_filters:  List[str] = [] # [] means print all categories
    receives_all:      bool = False  # True for expo — bypasses filters

class TerminalPeripheral(BaseModel):
    terminal_id:              str
    mac_address:              str
    device_type:              str    # 'dejavoo_spin' | 'mock'
    ip_address:               str
    is_active:                bool = True
    paired_receipt_printer_mac: Optional[str] = None # resolves receipt after payment
    print_customer_copy:      bool = True
    print_merchant_copy:      bool = True   # card only
    print_itemized_copy:      bool = False
    supported_languages:      List[str] = ['en', 'es', 'it']
    tip_suggestion_percentages: List[int] = [15, 18, 20]
    tip_calculation_base:     str = 'pretax'  # 'pretax' or 'posttax'
