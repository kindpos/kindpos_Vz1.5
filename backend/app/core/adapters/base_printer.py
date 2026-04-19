"""
KINDpos Printer Adapter — Base Interface Contract
===================================================
Nice. Dependable. Yours.

This module defines the universal interface that every printer adapter
must implement. KINDpos doesn't care what printer you have — Epson,
Star, Bixolon, whatever. If it implements this contract, it works.

"Keep your printers. We just swap the brain."

Architecture:
    - PrinterType: What hardware is it (thermal, impact, label)
    - PrinterRole: What job does it do (receipt, kitchen, bar, custom)
    - PrintJob: The payload sent to any printer
    - BasePrinter: The abstract contract every adapter implements

All printer actions are event-sourced via the EventType enum in events.py.
Nothing happens without a record in the Event Ledger.

File location: backend/app/core/adapters/base_printer.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid


# =============================================================
# SECTION 1: Enums — The Shared Vocabulary
# =============================================================

class PrinterType(Enum):
    """
    Hardware type of the printer.
    Determines how content is physically rendered.

    THERMAL  — Receipt printers. Fast, auto-cut, quiet.
               Keep these in FOH. Thermal paper + hot kitchen = bad time.
    IMPACT   — Kitchen printers. Dot matrix, ribbon-based.
               Built to survive heat, grease, and chaos.
    LABEL    — Future: prep labels, allergen tags, etc.
    """
    THERMAL = "thermal"
    IMPACT = "impact"
    LABEL = "label"


class PrinterStatus(Enum):
    """
    Current operational status of a printer.
    Reported by the adapter, logged in the Event Ledger.
    """
    ONLINE = "online"           # Ready to print
    OFFLINE = "offline"         # Not responding
    PAPER_OUT = "paper_out"     # Needs paper/ribbon
    COVER_OPEN = "cover_open"   # Lid is open
    JAM = "jam"                 # Paper jam
    OVERHEATED = "overheated"   # Print head too hot
    REBOOTING = "rebooting"     # Scheduled maintenance reboot


class PrintJobType(Enum):
    """
    What kind of document is being printed.
    Determines content layout.
    """
    KITCHEN_TICKET = "kitchen_ticket"   # Order items for the kitchen
    RECEIPT = "receipt"                 # Customer-facing itemized check
    REPORT = "report"                  # End of day, shift summary, etc.
    REPRINT = "reprint"                # Deliberate reprint (separate event from original)


class OrderContext(Enum):
    """
    How the order is being fulfilled.
    Affects what info appears on the ticket.
    e.g., delivery tickets include address, dine-in includes table/seat.
    """
    DINE_IN = "dine_in"
    TAKEOUT = "takeout"
    DELIVERY = "delivery"


class CutType(Enum):
    """
    How to finish the printed document.
    FULL    — Clean cut, paper drops. Typical for thermal receipts.
    PARTIAL — Cut with a tab holding the paper. Common for thermal.
    TEAR    — No auto-cut. Staff tears at the serrated edge.
              Standard for impact/kitchen printers.
    """
    FULL = "full"
    PARTIAL = "partial"
    TEAR = "tear"


class PrintJobPriority(Enum):
    """
    Priority level for print jobs.
    RUSH orders get a visual indicator on the printed ticket
    and jump to the front of the print queue.
    """
    NORMAL = "normal"
    RUSH = "rush"


# =============================================================
# SECTION 1B: Data Classes
# =============================================================

@dataclass
class PrinterConfig:
    """
    Configuration for a registered printer.
    Set during hardware discovery/setup, stored as events.

    Operators set this up once during onboarding.
    Smart defaults mean it works even if they skip optional fields.
    """
    printer_id: str                             # Unique ID (auto-generated or from discovery)
    name: str                                   # Operator-assigned name ("Kitchen 1", "Front Register")
    printer_type: PrinterType                   # Thermal, impact, or label
    role: str                                   # "receipt", "kitchen", "bar", or custom string
    connection_string: str                      # USB path, IP address, etc.
    location_tag: Optional[str] = None          # Optional: "hot line", "front counter", etc.
    fallback_printer_id: Optional[str] = None   # Optional: designated backup printer
    cut_type: CutType = CutType.FULL            # How to finish prints (default: full cut)
    operating_hours_start: Optional[str] = None # For maintenance scheduling (e.g., "06:00")
    operating_hours_end: Optional[str] = None   # For maintenance scheduling (e.g., "23:00")
    is_active: bool = True                      # Can be deactivated without removing


@dataclass
class PrintJobContent:
    """
    The actual content to be printed.
    Standard layouts per job type — kitchen tickets look like kitchen tickets,
    receipts look like receipts. Set up once, stays that way.
    """
    header_lines: List[str] = field(default_factory=list)   # Restaurant name, order info
    body_lines: List[str] = field(default_factory=list)     # Items, modifiers, details
    footer_lines: List[str] = field(default_factory=list)   # Totals, payment info, messages
    metadata: Dict[str, Any] = field(default_factory=dict)  # Extra context (table, server, address, etc.)


@dataclass
class PrintJob:
    """
    The complete payload sent to a printer adapter.

    Every print job gets a unique ID for double-print prevention.
    The Event Ledger checks this ID before allowing execution.
    If this job_id has already been printed, it blocks.
    Deliberate reprints use PrintJobType.REPRINT with a new job_id
    but reference the original via source_job_id.
    """
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str = ""                                  # Which order this belongs to
    job_type: PrintJobType = PrintJobType.KITCHEN_TICKET
    order_context: OrderContext = OrderContext.DINE_IN
    priority: PrintJobPriority = PrintJobPriority.NORMAL
    content: PrintJobContent = field(default_factory=PrintJobContent)
    target_role: str = "kitchen"                        # Which printer role should handle this
    target_printer_id: Optional[str] = None             # Specific printer override (optional)
    source_job_id: Optional[str] = None                 # For reprints: references the original job
    terminal_id: str = ""                               # Which terminal sent this
    server_name: str = ""                               # Who placed the order
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_reprint(self) -> bool:
        """A reprint always references an original job."""
        return self.job_type == PrintJobType.REPRINT and self.source_job_id is not None

    @property
    def is_rush(self) -> bool:
        return self.priority == PrintJobPriority.RUSH


@dataclass
class PrintResult:
    """
    What comes back after a print attempt.
    Success or failure, with details for the Event Ledger.
    """
    success: bool
    job_id: str
    printer_id: str
    message: str = ""                       # Human-readable status
    error_code: Optional[str] = None        # Machine-readable error
    retry_count: int = 0                    # How many retries were attempted
    rerouted_from: Optional[str] = None     # If this was a reroute, original printer ID
    timestamp: datetime = field(default_factory=datetime.now)


# =============================================================
# SECTION 2: Abstract Base Class — The Contract
# =============================================================
# Every printer adapter must implement this interface.
# The adapter is a translator — it speaks KINDpos on one side
# and hardware protocol on the other.
#
# The adapter does NOT handle:
#   - Double-print prevention (that's the PrinterManager + Event Ledger)
#   - Retry logic (that's the PrinterManager)
#   - Fallback/rerouting (that's the PrinterManager)
#   - Manager alerts (that's the PrinterManager + Messenger)
#
# The adapter ONLY handles:
#   - Connecting to the physical hardware
#   - Translating a PrintJob into hardware commands
#   - Reporting its status honestly
#   - Executing cuts and drawer kicks
#   - Rebooting when told to
# =============================================================

class BasePrinter(ABC):
    """
    Abstract base class for all printer adapters.

    Every printer in the KINDpos ecosystem — Epson, Star, Bixolon,
    whatever — implements this contract. The adapter is a translator:
    KINDpos speaks, hardware listens.

    Usage:
        class EpsonThermalAdapter(BasePrinter):
            def print_job(self, job: PrintJob) -> PrintResult:
                # Translate PrintJob into ESC/POS commands
                # Send to Epson via USB
                # Return success or failure

        class StarImpactAdapter(BasePrinter):
            def print_job(self, job: PrintJob) -> PrintResult:
                # Translate PrintJob into Star protocol
                # Send to Star via network
                # Return success or failure

    The PrinterManager handles all the smart logic (retries, rerouting,
    double-print prevention). The adapter just talks to hardware.
    """

    def __init__(self, config: PrinterConfig):
        """
        Initialize with a PrinterConfig.
        Every adapter knows who it is, what it does, and where it lives.
        """
        self._config = config
        self._status = PrinterStatus.OFFLINE  # Start offline until connect() succeeds
        self._connected = False

    # -----------------------------------------------------------------
    # Identity — Who am I?
    # -----------------------------------------------------------------

    @property
    def printer_id(self) -> str:
        """Unique identifier for this printer."""
        return self._config.printer_id

    @property
    def name(self) -> str:
        """Operator-assigned display name."""
        return self._config.name

    @property
    def printer_type(self) -> PrinterType:
        """Hardware type: thermal, impact, or label."""
        return self._config.printer_type

    @property
    def role(self) -> str:
        """Assigned role: receipt, kitchen, bar, or custom."""
        return self._config.role

    @property
    def location_tag(self) -> Optional[str]:
        """Optional location: hot line, front counter, etc."""
        return self._config.location_tag

    @property
    def fallback_printer_id(self) -> Optional[str]:
        """Designated backup printer, if any."""
        return self._config.fallback_printer_id

    @property
    def status(self) -> PrinterStatus:
        """Current operational status."""
        return self._status

    @property
    def is_active(self) -> bool:
        """Whether this printer is enabled for use."""
        return self._config.is_active

    def get_config(self) -> PrinterConfig:
        """Return the full printer configuration."""
        return self._config

    # -----------------------------------------------------------------
    # Connection — Talk to the hardware
    # -----------------------------------------------------------------

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to the physical printer.

        This might mean:
            - Opening a USB device handle
            - Connecting to a network IP
            - Initializing a serial port

        Returns True if connection was successful.
        Sets status to ONLINE on success, OFFLINE on failure.
        """
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """
        Clean shutdown of the printer connection.

        Flush any pending data, release the device handle.
        Returns True if disconnection was clean.
        Sets status to OFFLINE.
        """
        pass

    def is_connected(self) -> bool:
        """
        Quick check: are we still talking to the hardware?
        Does not perform a full status query — just checks
        whether the connection handle is alive.
        """
        return self._connected

    # -----------------------------------------------------------------
    # Core Operations — The main job
    # -----------------------------------------------------------------

    @abstractmethod
    def print_job(self, job: PrintJob) -> PrintResult:
        """
        Send a print job to the hardware.

        This is the core operation. The adapter translates the PrintJob
        into whatever protocol the hardware speaks (ESC/POS, Star Line Mode,
        etc.) and sends it.

        The adapter tries ONCE. It does not retry — that's the
        PrinterManager's job. It just reports honestly:
            - Success: the job printed
            - Failure: why it didn't (paper out, offline, jam, etc.)

        Args:
            job: The PrintJob containing content and metadata

        Returns:
            PrintResult with success/failure and details
        """
        pass

    @abstractmethod
    def check_status(self) -> PrinterStatus:
        """
        Query the hardware for its current status.

        Asks the printer directly: are you online? Do you have paper?
        Is your cover closed? Is the head overheated?

        Updates self._status and returns the result.
        Different printers report different levels of detail —
        some only know online/offline, some report everything.
        The adapter does its best with what the hardware provides.
        """
        pass

    @abstractmethod
    def cut_paper(self, cut_type: Optional[CutType] = None) -> bool:
        """
        Execute a paper cut.

        If cut_type is None, uses the default from PrinterConfig.
        Thermal printers typically support FULL and PARTIAL.
        Impact printers typically use TEAR (no auto-cut).

        Returns True if the cut command was sent successfully.
        For TEAR type, this is essentially a no-op but returns True.
        """
        pass

    @abstractmethod
    def open_drawer(self) -> bool:
        """
        Kick the cash drawer open.

        Cash drawers connect to the printer via the DK (drawer kick) port.
        This sends the electrical pulse to pop it open.

        Returns True if the drawer kick command was sent successfully.
        Not all printers have a drawer connected — adapter should
        return False with a clear message if no drawer is detected.
        """
        pass

    # -----------------------------------------------------------------
    # Maintenance — Keep it healthy
    # -----------------------------------------------------------------

    @abstractmethod
    def reboot(self) -> bool:
        """
        Perform a printer reboot.

        Used for scheduled off-hours maintenance to:
            - Clear the print buffer
            - Let the print head cool down
            - Reset firmware state
            - Extend hardware lifespan

        The PrinterManager schedules this outside operating hours.
        The adapter handles the actual reboot sequence for its hardware.

        Returns True if the reboot command was sent successfully.
        """
        pass

    # -----------------------------------------------------------------
    # Convenience — Common checks
    # -----------------------------------------------------------------

    def is_ready(self) -> bool:
        """
        Is this printer ready to accept a job right now?
        Connected, online, active, and not rebooting.
        """
        return (
            self._connected
            and self._status == PrinterStatus.ONLINE
            and self._config.is_active
        )

    def can_handle_role(self, role: str) -> bool:
        """
        Can this printer handle jobs for the given role?
        Simple string match against the assigned role.
        """
        return self._config.role.lower() == role.lower()

    def matches_type(self, printer_type: PrinterType) -> bool:
        """
        Is this printer the specified hardware type?
        Used by PrinterManager for fallback routing —
        impact printers fall back to impact, thermal to thermal.
        """
        return self._config.printer_type == printer_type

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"id='{self.printer_id}' "
            f"name='{self.name}' "
            f"type={self.printer_type.value} "
            f"role='{self.role}' "
            f"status={self.status.value}>"
        )
