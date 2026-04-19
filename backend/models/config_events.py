from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class StoreInfo(BaseModel):
    restaurant_name: str = "KINDpos"
    legal_entity_name: Optional[str] = None
    address_line_1: str = ""
    address_line_2: Optional[str] = None
    city: str = ""
    state: str = ""
    zip: str = ""
    phone: str = ""
    email: Optional[str] = None
    website: Optional[str] = None

class CCProcessingRate(BaseModel):
    rate_percent: float = 2.9
    per_transaction_fee: float = 0.30

class TaxRule(BaseModel):
    tax_rule_id: str
    name: str
    rate_percent: float
    applies_to: str # "all" or "category"
    category_id: Optional[str] = None

class OperatingHours(BaseModel):
    open: str
    close: str
    enabled: bool

class StoreOperatingHours(BaseModel):
    hours: Dict[str, OperatingHours]

class StoreOrderTypes(BaseModel):
    enabled_types: List[str]

class StoreAutoGratuity(BaseModel):
    enabled: bool
    party_size_threshold: int = 6
    rate_percent: float = 20.0
    applies_to_order_types: List[str] = ["dine_in"]

class StoreConfigBundle(BaseModel):
    info: StoreInfo
    tax_rules: List[TaxRule]
    cc_processing: CCProcessingRate
    operating_hours: Dict[str, OperatingHours]
    order_types: StoreOrderTypes
    auto_gratuity: StoreAutoGratuity
    cash_discount_rate: float = 0.0

# Employee Models
class Role(BaseModel):
    role_id: str
    name: str
    permission_level: str  # Standard, Elevated, Manager
    permissions: Dict[str, bool]
    tipout_eligible: bool
    can_receive_tips: bool
    can_be_tipped_out_to: bool

class Employee(BaseModel):
    employee_id: str
    first_name: str
    last_name: str
    display_name: str
    role_ids: List[str] = []
    role_id: Optional[str] = None  # backward compat — migrated to role_ids
    pin: str
    hourly_rate: float
    permissions_override: Optional[Dict[str, bool]] = None
    active: bool = True

    def __init__(self, **data):
        if 'role_id' in data and 'role_ids' not in data:
            rid = data.pop('role_id')
            data['role_ids'] = [rid] if rid else []
        super().__init__(**data)

class TipoutRule(BaseModel):
    rule_id: str
    role_from: str
    role_to: str
    percentage: float
    calculation_base: str # Net Sales, Gross Tips, Net Tips
    # Optional category filter. When non-empty and calculation_base is
    # "Net Sales", the basis is the sum of net sales for items in these
    # categories only (typically applied per-server, e.g. "2% of
    # alcohol net sales to bar"). Empty list → full net sales.
    categories: List[str] = []

# Menu Models
class MenuItem(BaseModel):
    item_id: str
    name: str
    category_id: str
    price: float
    description: Optional[str] = None
    kitchen_name: Optional[str] = None
    tax_rule_id: Optional[str] = None
    revenue_category: str # Food, Beverage, Alcohol
    prep_time: int = 0
    print_station: Optional[str] = None
    allergens: List[str] = []
    active: bool = True
    # Transient stockout flag — toggled by MENU_ITEM_86D / MENU_ITEM_RESTORED.
    is_86ed: bool = False

class MenuCategory(BaseModel):
    category_id: str
    name: str
    display_order: int
    hex_color: str
    tax_rule_id: Optional[str] = None
    enable_placement: bool = False
    half_placement: bool = False
    active: bool = True

# Floor Plan Models
class TableElement(BaseModel):
    id: str
    name: str
    seats: int
    section_id: str
    shape: str
    x: int
    y: int
    width: int
    height: int
    rotation: int
    active: bool = True

class StructureElement(BaseModel):
    id: str
    type: str
    x: int
    y: int
    width: Optional[int] = None
    height: Optional[int] = None
    x2: Optional[int] = None
    y2: Optional[int] = None
    label: Optional[str] = None

class FixtureElement(BaseModel):
    id: str
    type: str
    device_id: Optional[str] = None
    x: int
    y: int
    width: int
    height: int
    label: Optional[str] = None

class FloorPlanLayout(BaseModel):
    canvas: Dict[str, int]
    tables: List[TableElement]
    structures: List[StructureElement]
    fixtures: List[FixtureElement]

class Section(BaseModel):
    section_id: str
    name: str
    color: str
    active: bool = True

# Hardware Models
class Terminal(BaseModel):
    terminal_id: str
    name: str
    role: str
    default_section_id: Optional[str] = None
    training_mode: bool = False

class Printer(BaseModel):
    printer_id: str
    name: str
    station: str
    ip_address: str
    mac_address: str
    paper_width: str = "80mm"
    print_logo: bool = True
    active: bool = True

class RoutingMatrix(BaseModel):
    matrix: Dict[str, List[str]] # category_id -> list of printer_ids

# Reporting Models
class DashboardConfig(BaseModel):
    widgets: List[Dict]

class CustomReport(BaseModel):
    report_id: str
    name: str
    query_definition: Dict

class AccountsMapping(BaseModel):
    accounts: Dict[str, str]

class PendingChange(BaseModel):
    event_type: str
    payload: Dict
