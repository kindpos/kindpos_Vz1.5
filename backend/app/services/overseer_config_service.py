from typing import List, Dict, Any, Optional, Callable, TypeVar
from app.core.event_ledger import EventLedger
from app.core.events import EventType, Event
from app.models.config_events import (
    Role, Employee, TipoutRule,
    MenuItem, MenuCategory, ModifierGroup,
    MandatoryAssignment, UniversalAssignment,
    Section, FloorPlanLayout,
    Terminal, Printer, RoutingMatrix,
    DashboardConfig, CustomReport, AccountsMapping
)

T = TypeVar("T")


class _ProjectionCache:
    """Simple cache that tracks the max sequence number seen for a projection."""
    __slots__ = ("_seq", "_data")

    def __init__(self):
        self._seq: int = -1
        self._data: Any = None

    def get(self, current_seq: int):
        if self._seq == current_seq:
            return self._data
        return None

    def set(self, seq: int, data: Any):
        self._seq = seq
        self._data = data


class OverseerConfigService:
    def __init__(self, ledger: EventLedger):
        self.ledger = ledger
        self._cache: Dict[str, _ProjectionCache] = {}

    def _get_cache(self, key: str) -> _ProjectionCache:
        if key not in self._cache:
            self._cache[key] = _ProjectionCache()
        return self._cache[key]

    async def _max_seq(self) -> int:
        cursor = await self.ledger._db.execute(
            "SELECT MAX(sequence_number) FROM events"
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] else 0

    async def get_roles(self) -> List[Role]:
        cache = self._get_cache("roles")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.EMPLOYEE_ROLE_CREATED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.EMPLOYEE_ROLE_UPDATED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.EMPLOYEE_ROLE_DELETED, limit=1000)
        events.sort(key=lambda x: x.sequence_number or 0)

        roles = {}
        for e in events:
            payload = e.payload
            rid = payload["role_id"]
            if e.event_type == EventType.EMPLOYEE_ROLE_DELETED:
                roles.pop(rid, None)
            else:
                roles[rid] = Role(**payload)
        result = list(roles.values())
        cache.set(seq, result)
        return result

    async def get_employees(self) -> List[Employee]:
        cache = self._get_cache("employees")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.EMPLOYEE_CREATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.EMPLOYEE_UPDATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.EMPLOYEE_DELETED, limit=5000)
        events.sort(key=lambda x: x.sequence_number or 0)

        emps = {}
        for e in events:
            payload = e.payload
            eid = payload["employee_id"]
            if e.event_type == EventType.EMPLOYEE_DELETED:
                emps.pop(eid, None)
            else:
                emps[eid] = Employee(**payload)
        result = list(emps.values())
        cache.set(seq, result)
        return result

    async def get_tipout_rules(self) -> List[TipoutRule]:
        cache = self._get_cache("tipout_rules")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.TIPOUT_RULE_CREATED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.TIPOUT_RULE_UPDATED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.TIPOUT_RULE_DELETED, limit=1000)
        events.sort(key=lambda x: x.sequence_number or 0)

        rules = {}
        for e in events:
            payload = e.payload
            rid = payload["rule_id"]
            if e.event_type == EventType.TIPOUT_RULE_DELETED:
                rules.pop(rid, None)
            else:
                rules[rid] = TipoutRule(**payload)
        result = list(rules.values())
        cache.set(seq, result)
        return result

    async def get_menu_categories(self) -> List[MenuCategory]:
        cache = self._get_cache("menu_categories")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.MENU_CATEGORY_CREATED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.MENU_CATEGORY_UPDATED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.MENU_CATEGORY_DELETED, limit=1000)
        events.sort(key=lambda x: x.sequence_number or 0)

        cats = {}
        for e in events:
            payload = e.payload
            cid = payload["category_id"]
            if e.event_type == EventType.MENU_CATEGORY_DELETED:
                cats.pop(cid, None)
            else:
                cats[cid] = MenuCategory(**payload)
        result = list(cats.values())
        cache.set(seq, result)
        return result

    async def get_menu_items(self) -> List[MenuItem]:
        cache = self._get_cache("menu_items")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        # CREATED / UPDATED / DELETED handle the item's lifecycle.
        # 86D / RESTORED toggle the temporary `is_86ed` stockout flag
        # without removing the item from the projection — an 86'd item
        # stays on the menu so the POS can show it greyed out, but
        # order-entry must refuse to add one.
        events = await self.ledger.get_events_by_type(EventType.MENU_ITEM_CREATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MENU_ITEM_UPDATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MENU_ITEM_DELETED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MENU_ITEM_86D, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MENU_ITEM_RESTORED, limit=5000)
        events.sort(key=lambda x: x.sequence_number or 0)

        items = {}
        for e in events:
            payload = e.payload
            iid = payload["item_id"]
            if e.event_type == EventType.MENU_ITEM_DELETED:
                items.pop(iid, None)
            elif e.event_type == EventType.MENU_ITEM_86D:
                existing = items.get(iid)
                if existing is not None:
                    items[iid] = existing.model_copy(update={"is_86ed": True})
            elif e.event_type == EventType.MENU_ITEM_RESTORED:
                existing = items.get(iid)
                if existing is not None:
                    items[iid] = existing.model_copy(update={"is_86ed": False})
            else:
                items[iid] = MenuItem(**payload)
        result = list(items.values())
        cache.set(seq, result)
        return result

    async def get_modifier_groups(self) -> List[ModifierGroup]:
        cache = self._get_cache("modifier_groups")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.MODIFIER_GROUP_CREATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MODIFIER_GROUP_UPDATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MODIFIER_GROUP_DELETED, limit=5000)
        events.sort(key=lambda x: x.sequence_number or 0)

        groups: Dict[str, Dict[str, Any]] = {}
        for e in events:
            payload = e.payload
            gid = payload.get("group_id")
            if not gid:
                continue
            if e.event_type == EventType.MODIFIER_GROUP_DELETED:
                groups.pop(gid, None)
            elif e.event_type == EventType.MODIFIER_GROUP_CREATED:
                groups[gid] = dict(payload)
            else:  # MODIFIER_GROUP_UPDATED — merge onto existing to preserve fields
                existing = groups.get(gid, {})
                existing.update(payload)
                groups[gid] = existing

        result = [ModifierGroup(**g) for g in groups.values()]
        cache.set(seq, result)
        return result

    async def get_mandatory_assignments(self) -> List[MandatoryAssignment]:
        cache = self._get_cache("mandatory_assignments")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.MODIFIER_MANDATORY_CREATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MODIFIER_MANDATORY_UPDATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MODIFIER_MANDATORY_DELETED, limit=5000)
        events.sort(key=lambda x: x.sequence_number or 0)

        assignments: Dict[str, Dict[str, Any]] = {}
        for e in events:
            payload = e.payload
            aid = payload.get("assignment_id")
            if not aid:
                continue
            if e.event_type == EventType.MODIFIER_MANDATORY_DELETED:
                assignments.pop(aid, None)
            elif e.event_type == EventType.MODIFIER_MANDATORY_CREATED:
                assignments[aid] = dict(payload)
            else:
                existing = assignments.get(aid, {})
                existing.update(payload)
                assignments[aid] = existing

        result = [MandatoryAssignment(**a) for a in assignments.values()]
        cache.set(seq, result)
        return result

    async def get_universal_assignments(self) -> List[UniversalAssignment]:
        cache = self._get_cache("universal_assignments")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.MODIFIER_UNIVERSAL_CREATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MODIFIER_UNIVERSAL_UPDATED, limit=5000)
        events += await self.ledger.get_events_by_type(EventType.MODIFIER_UNIVERSAL_DELETED, limit=5000)
        events.sort(key=lambda x: x.sequence_number or 0)

        assignments: Dict[str, Dict[str, Any]] = {}
        for e in events:
            payload = e.payload
            aid = payload.get("assignment_id")
            if not aid:
                continue
            if e.event_type == EventType.MODIFIER_UNIVERSAL_DELETED:
                assignments.pop(aid, None)
            elif e.event_type == EventType.MODIFIER_UNIVERSAL_CREATED:
                assignments[aid] = dict(payload)
            else:
                existing = assignments.get(aid, {})
                existing.update(payload)
                assignments[aid] = existing

        result = [UniversalAssignment(**a) for a in assignments.values()]
        cache.set(seq, result)
        return result

    async def get_floorplan_sections(self) -> List[Section]:
        cache = self._get_cache("floorplan_sections")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.FLOORPLAN_SECTION_CREATED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.FLOORPLAN_SECTION_UPDATED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.FLOORPLAN_SECTION_DELETED, limit=1000)
        events.sort(key=lambda x: x.sequence_number or 0)

        sections = {}
        for e in events:
            payload = e.payload
            sid = payload["section_id"]
            if e.event_type == EventType.FLOORPLAN_SECTION_DELETED:
                sections.pop(sid, None)
            else:
                sections[sid] = Section(**payload)
        result = list(sections.values())
        cache.set(seq, result)
        return result

    async def get_floorplan_layout(self) -> FloorPlanLayout:
        cache = self._get_cache("floorplan_layout")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.FLOORPLAN_LAYOUT_UPDATED, limit=1000)
        if not events:
            result = FloorPlanLayout(canvas={"width": 1200, "height": 800}, tables=[], structures=[], fixtures=[])
        else:
            events.sort(key=lambda x: x.sequence_number or 0)
            latest = events[-1]
            result = FloorPlanLayout(**latest.payload)
        cache.set(seq, result)
        return result

    async def get_terminals(self) -> List[Terminal]:
        cache = self._get_cache("terminals")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.TERMINAL_REGISTERED, limit=1000)
        events += await self.ledger.get_events_by_type(EventType.TERMINAL_UPDATED, limit=1000)
        events.sort(key=lambda x: x.sequence_number or 0)

        terms = {}
        for e in events:
            payload = e.payload
            tid = payload["terminal_id"]
            # Merge or overwrite
            if tid in terms:
                updated_payload = terms[tid].model_dump()
                updated_payload.update(payload)
                terms[tid] = Terminal(**updated_payload)
            else:
                terms[tid] = Terminal(**payload)
        result = list(terms.values())
        cache.set(seq, result)
        return result

    async def get_printers(self) -> List[Printer]:
        cache = self._get_cache("printers")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.PRINTER_REGISTERED, limit=1000)
        events.sort(key=lambda x: x.sequence_number or 0)

        printers = {}
        for e in events:
            payload = e.payload
            pid = payload["printer_id"]
            printers[pid] = Printer(**payload)
        result = list(printers.values())
        cache.set(seq, result)
        return result

    async def get_routing_matrix(self) -> RoutingMatrix:
        cache = self._get_cache("routing_matrix")
        seq = await self._max_seq()
        cached = cache.get(seq)
        if cached is not None:
            return cached

        events = await self.ledger.get_events_by_type(EventType.ROUTING_MATRIX_UPDATED, limit=1000)
        if not events:
            result = RoutingMatrix(matrix={})
        else:
            events.sort(key=lambda x: x.sequence_number or 0)
            result = RoutingMatrix(**events[-1].payload)
        cache.set(seq, result)
        return result
