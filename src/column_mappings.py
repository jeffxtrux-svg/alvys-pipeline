"""
Column mappings v4 — full enrichment pass.

Each entry is (master_column_name, accessor) where accessor is:
  • a string  — dot-notation path through the JSON response
  • a callable — function(record) -> value, for computed/enriched columns
  • None     — placeholder for truly-unavailable fields (UI-only, real-time)
"""
from src import lookups
from src.lookups import (
    trip_for_load, load_for_trip, trips_count,
    customer_for_load, customer_invoice_for_load, carrier_invoice_for_load,
    driver1_rate, driver1_rate_via_trip,
    _get_nested,
)
from src.transformers import (
    _first_stop_name, _last_stop_name, _load_lane,
    _stop_fcfs, _stop_appt, _first_equipment,
)


# ===========================================================================
# Lookup-driven accessors
# ===========================================================================
def _name_from_id(table_attr: str, path: str):
    """Resolve an ID via a lookup table."""
    def fn(record: dict):
        rid = _get_nested(record, path)
        if not rid:
            return None
        table = getattr(lookups, table_attr)
        return table.get(rid)
    return fn


def _name_from_id_via_trip(table_attr: str, path: str):
    """For Load records: hop to trip first, then resolve ID via lookup."""
    def fn(load_record: dict):
        trip = trip_for_load(load_record)
        if not trip:
            return None
        rid = _get_nested(trip, path)
        if not rid:
            return None
        table = getattr(lookups, table_attr)
        return table.get(rid)
    return fn


def _name_from_id_via_load(table_attr: str, path: str):
    """For Trip records: hop to load first, then resolve ID via lookup."""
    def fn(trip_record: dict):
        load = load_for_trip(trip_record)
        if not load:
            return None
        rid = _get_nested(load, path)
        if not rid:
            return None
        table = getattr(lookups, table_attr)
        return table.get(rid)
    return fn


def _from_trip(path: str):
    """For Load records: get a field from the joined trip."""
    def fn(load_record: dict):
        trip = trip_for_load(load_record)
        if not trip:
            return None
        return _get_nested(trip, path)
    return fn


def _from_load(path: str):
    """For Trip records: get a field from the joined load."""
    def fn(trip_record: dict):
        load = load_for_trip(trip_record)
        if not load:
            return None
        return _get_nested(load, path)
    return fn


# ===========================================================================
# Computed columns
# ===========================================================================
def _gross_margin(record: dict):
    """Customer Revenue - Trip Value. Works on Load or Trip records."""
    if "LoadNumber" in record and "Stops" in record and "CustomerRate" in record:
        revenue = _get_nested(record, "CustomerRate.Amount")
        trip = trip_for_load(record)
        cost = _get_nested(trip, "TripValue.Amount") if trip else None
    else:
        cost = _get_nested(record, "TripValue.Amount")
        load = load_for_trip(record)
        revenue = _get_nested(load, "CustomerRate.Amount") if load else None
    if revenue is None or cost is None:
        return None
    try:
        return float(revenue) - float(cost)
    except (TypeError, ValueError):
        return None


def _appointments_verified(record: dict):
    stops = record.get("Stops")
    if not isinstance(stops, list) or not stops:
        return None
    confirmed = [s.get("AppointmentConfirmed") for s in stops if isinstance(s, dict)]
    return all(confirmed) if confirmed else None


def _zero(record: dict):
    """For columns that are always 0 in the original master file."""
    return 0


def _zero_default(path: str):
    """Get a field value; default to 0 if missing. For amount columns that the
    original master always has populated (mostly with 0, occasionally a real value)."""
    def fn(record: dict):
        v = _get_nested(record, path)
        return v if v is not None else 0
    return fn


def _zero_default_via_load(path: str):
    """For Trip records: get from joined load, default to 0."""
    def fn(trip: dict):
        load = load_for_trip(trip)
        if not load:
            return 0
        v = _get_nested(load, path)
        return v if v is not None else 0
    return fn


def _driver1_rate_or_zero(rate_type: str):
    inner = driver1_rate(rate_type)
    def fn(record: dict):
        v = inner(record)
        return v if v is not None else 0
    return fn


def _driver1_rate_via_trip_or_zero(rate_type: str):
    inner = driver1_rate_via_trip(rate_type)
    def fn(record: dict):
        v = inner(record)
        return v if v is not None else 0
    return fn


# --- Office name resolution -------------------------------------------------
# Maps InvoiceAs / TenderAs raw values to the Office name format used in the
# original Power BI source. The /offices endpoint doesn't exist in this Alvys
# tenant, so we normalize from InvoiceAs which always has the subsidiary name.
OFFICE_NAME_NORMALIZATION = {
    "X-TRUX INC":               "X-Trux, Inc",
    "X-LINX INC":               "X-Linx, Inc.",
    "X-LINX INC (BROKERAGE)":   "X-Linx, Inc.",
    "XFREIGHT":                 "XFreight",
    "QUOTE":                    "QUOTE",
}


def _normalize_office_name(name):
    if not name:
        return None
    return OFFICE_NAME_NORMALIZATION.get(str(name).strip().upper(), name)


def _office_name(load: dict):
    """Resolve OfficeId via offices lookup; fall back to InvoiceAs (normalized)."""
    office_id = load.get("OfficeId")
    if office_id and office_id in lookups.offices:
        return lookups.offices[office_id]
    # Fallback: InvoiceAs normalized to match original Power BI source casing
    return _normalize_office_name(load.get("InvoiceAs"))


def _office_name_via_trip(trip: dict):
    """For Trip records — via joined load, fall back to normalized TenderAs."""
    load = load_for_trip(trip)
    if load:
        name = _office_name(load)
        if name:
            return name
    return _normalize_office_name(trip.get("TenderAs"))


# --- Carrier label ----------------------------------------------------------
def _asset_label(subsidiary_name):
    """Convert 'X-TRUX INC' or 'X-Trux, Inc' to 'X-TRUX Asset' style."""
    if not subsidiary_name:
        return None
    name = str(subsidiary_name).upper().strip()
    for suf in [", INC.", ", INC", " INC.", " INC", " LLC.", " LLC", ", LLC"]:
        if name.endswith(suf):
            name = name[: -len(suf)].rstrip(",.").strip()
            break
    return f"{name} Asset"


def _carrier_label_trip(trip: dict):
    """For Trip records: 'X-TRUX Asset' if asset, else carrier name."""
    tender_type = trip.get("TenderAsSubsidiaryType")
    tender_as = trip.get("TenderAs")
    # TenderAsSubsidiaryType == 'Carrier' means asset-based
    if tender_type == "Carrier" and tender_as:
        return _asset_label(tender_as)
    # Brokered: lookup carrier name
    carrier_id = _get_nested(trip, "Carrier.Id") or trip.get("CarrierId")
    if carrier_id and carrier_id in lookups.carriers:
        return lookups.carriers[carrier_id]
    # Last resort
    return tender_as


def _carrier_label_load(load: dict):
    """For Load records: go via joined trip."""
    trip = trip_for_load(load)
    if trip:
        result = _carrier_label_trip(trip)
        if result:
            return result
    return _asset_label(load.get("InvoiceAs"))


# --- Driver 2 / Carrier Sales Agent: 'Multiple Trips' aggregation ----------
def _driver2_load(load: dict):
    """For Load records: 'Multiple Trips' if >1 trip, else the trip's Driver 2."""
    if trips_count(load) > 1:
        return "Multiple Trips"
    trip = trip_for_load(load)
    if not trip:
        return None
    d2_id = _get_nested(trip, "Driver2.Id")
    return lookups.drivers.get(d2_id) if d2_id else None


def _carrier_sales_agent_load(load: dict):
    """Original master shows 'Multiple Carrier Sales Agents' for multi-trip loads."""
    if trips_count(load) > 1:
        return "Multiple Carrier Sales Agents"
    # Single trip: try the join'd trip's carrier sales agent (likely not in API)
    return None


# --- Notes formatting -------------------------------------------------------
def _format_notes_value(value):
    """Convert Notes list-of-objects into a newline-joined string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if not value:
            return None
        parts = []
        for n in value:
            if isinstance(n, dict):
                for key in ("Text", "Note", "Body", "Content", "Description", "Message"):
                    if n.get(key):
                        parts.append(str(n[key]))
                        break
                else:
                    parts.append(str(n))
            elif n:
                parts.append(str(n))
        return "\n".join(parts) if parts else None
    return str(value)


def _notes(record: dict):
    return _format_notes_value(record.get("Notes"))


def _notes_via_load(trip: dict):
    load = load_for_trip(trip)
    return _format_notes_value(load.get("Notes")) if load else None


# --- Fuel card lookups from truck FuelCards array ---------------------------
def _fuel_card_field(field_name: str):
    """field_name: 'CardNumber' | 'DeductFromName' | 'DeductFuel'"""
    def fn(fuel_record: dict):
        truck_id = fuel_record.get("TruckId")
        if not truck_id:
            return None
        card = lookups.truck_fuel_cards.get(truck_id)
        if not card:
            return None
        return card.get(field_name)
    return fn


# --- Factoring company ------------------------------------------------------
def _factoring_company_load(load: dict):
    """Try direct field, then via joined trip's carrier, then via own carrier lookup."""
    direct = load.get("CarrierFactoringCompany") or load.get("FactoringCompany")
    if direct:
        return direct
    trip = trip_for_load(load)
    carrier_id = _get_nested(trip, "Carrier.Id") if trip else None
    return lookups.factoring_by_carrier.get(carrier_id) if carrier_id else None


def _factoring_company_trip(trip: dict):
    direct = trip.get("CarrierFactoringCompany") or trip.get("FactoringCompany")
    if direct:
        return direct
    carrier_id = _get_nested(trip, "Carrier.Id")
    return lookups.factoring_by_carrier.get(carrier_id) if carrier_id else None


# --- Customer record accessors ----------------------------------------------
def _customer_field(field_names: list[str]):
    """For a Load record: get a field from the joined customer record.
    Tries multiple field names since we don't know exact API spelling."""
    def fn(load: dict):
        cust = customer_for_load(load)
        if not cust:
            return None
        for fn_ in field_names:
            v = _get_nested(cust, fn_)
            if v:
                return v
        return None
    return fn


def _customer_field_via_load(field_names: list[str]):
    """For a Trip record: hop to load → customer → field."""
    def fn(trip: dict):
        load = load_for_trip(trip)
        if not load:
            return None
        cust = customer_for_load(load)
        if not cust:
            return None
        for fn_ in field_names:
            v = _get_nested(cust, fn_)
            if v:
                return v
        return None
    return fn


def _user_via_customer(field_names: list[str]):
    """For a Load record: customer record → user ID field → users lookup name."""
    def fn(load: dict):
        cust = customer_for_load(load)
        if not cust:
            return None
        for fn_ in field_names:
            uid = _get_nested(cust, fn_)
            if uid:
                return lookups.users.get(uid)
        return None
    return fn


def _user_via_customer_via_load(field_names: list[str]):
    """For a Trip record: load → customer → user ID → user name."""
    def fn(trip: dict):
        load = load_for_trip(trip)
        if not load:
            return None
        cust = customer_for_load(load)
        if not cust:
            return None
        for fn_ in field_names:
            uid = _get_nested(cust, fn_)
            if uid:
                return lookups.users.get(uid)
        return None
    return fn


# --- Invoice accessors ------------------------------------------------------
def _customer_invoice_field(field_names: list[str]):
    """For a Load record: customer invoice → field. Tries multiple names."""
    def fn(load: dict):
        inv = customer_invoice_for_load(load)
        if not inv:
            return None
        for fn_ in field_names:
            v = _get_nested(inv, fn_)
            if v is not None:
                return v
        return None
    return fn


def _customer_invoice_field_via_load(field_names: list[str]):
    """For a Trip record: load → customer invoice → field."""
    def fn(trip: dict):
        load = load_for_trip(trip)
        if not load:
            return None
        inv = customer_invoice_for_load(load)
        if not inv:
            return None
        for fn_ in field_names:
            v = _get_nested(inv, fn_)
            if v is not None:
                return v
        return None
    return fn


def _carrier_invoice_field(field_names: list[str]):
    """For a Load record: carrier invoice → field."""
    def fn(load: dict):
        inv = carrier_invoice_for_load(load)
        if not inv:
            return None
        for fn_ in field_names:
            v = _get_nested(inv, fn_)
            if v is not None:
                return v
        return None
    return fn


def _carrier_invoice_field_via_load(field_names: list[str]):
    """For a Trip record: load → carrier invoice → field."""
    def fn(trip: dict):
        load = load_for_trip(trip)
        if not load:
            return None
        inv = carrier_invoice_for_load(load)
        if not inv:
            return None
        for fn_ in field_names:
            v = _get_nested(inv, fn_)
            if v is not None:
                return v
        return None
    return fn


# ===========================================================================
# LOADS — 108 columns
# ===========================================================================
LOADS_COLUMNS = [
    ("First Pick Arrived",                  "Stops.first.ArrivedAt"),
    ("First Pick Departed",                 "Stops.first.DepartedAt"),
    ("Last Drop Arrived",                   "Stops.last.ArrivedAt"),
    ("Last Drop Departed",                  "Stops.last.DepartedAt"),
    ("Posted Carrier Rate",                 _zero_default("PostedCarrierRate")),
    ("Carrier External Compliance Status",  None),
    ("Customer Miles",                      "CustomerMileage.Distance.Value"),
    ("Account Manager",                     _user_via_customer(["AccountManagerId", "AccountManager.Id"])),
    ("Carrier All-in Rate",                 _from_trip("TripValue.Amount")),
    ("Brokerage Status",                    "BrokerageStatus"),
    ("Date Imported",                       "CreatedAt"),
    ("Load Weight",                         "Weight"),
    ("Customer Sales Agent",                _name_from_id("users", "CustomerSalesAgentId")),
    ("Carrier Sales Agent",                 _carrier_sales_agent_load),
    ("Customer Service Representative",     _user_via_customer(["CustomerServiceRepresentativeId", "CSRId", "CustomerServiceRepId"])),
    ("Load Planner",                        _name_from_id("users", "CustomerLoadPlannerId")),
    ("Sales Manager",                       _user_via_customer(["SalesManagerId", "SalesManager.Id"])),
    ("Pickup Region",                       "PickupRegion"),
    ("Dropoff Region",                      "DropoffRegion"),
    ("Pickup Market",                       "PickupMarket"),
    ("Dropoff Market",                      "DropoffMarket"),
    ("Icons",                               None),                                   # UI-only
    ("Load #",                              "LoadNumber"),
    ("PO #",                                "PONumber"),
    ("Order #",                             "OrderNumber"),
    ("Load Type",                           "LoadType"),
    ("Equipment",                           _first_equipment),
    ("Reason Not Complete",                 "ReasonNotComplete"),
    ("Loaded Miles",                        _from_trip("LoadedMileage.Distance.Value")),
    ("Empty Miles",                         _from_trip("EmptyMileage.Distance.Value")),
    ("Loaded Dispatch Mileage",             _from_trip("LoadedMileage.Distance.Value")),
    ("Empty Dispatch Mileage",              _from_trip("EmptyMileage.Distance.Value")),
    ("Total Dispatch Mileage",              _from_trip("TotalMileage.Distance.Value")),
    ("Customer Revenue",                    "CustomerRate.Amount"),
    ("Driver Rate",                         _from_load("DriverRate.Amount")),
    ("Load Lane",                           _load_lane),
    ("Load Status",                         "Status"),
    ("First Pick Status",                   "Stops.first.Status"),
    ("Last Drop Status",                    "Stops.last.Status"),
    ("Customer",                            "CustomerName"),
    ("Invoice As",                          "InvoiceAs"),
    ("First Stop",                          _first_stop_name),
    ("Pick City",                           "Stops.first.Address.City"),
    ("Pick State",                          "Stops.first.Address.State"),
    ("Scheduled Pickup",                    "ScheduledPickupAt"),
    ("Last Stop",                           _last_stop_name),
    ("Drop City",                           "Stops.last.Address.City"),
    ("Drop State",                          "Stops.last.Address.State"),
    ("Scheduled Delivery",                  "ScheduledDeliveryAt"),
    ("Carrier",                             _carrier_label_load),
    ("Office",                              _office_name),
    ("Driver 1",                            _name_from_id_via_trip("drivers", "Driver1.Id")),
    ("Driver 2",                            _driver2_load),
    ("Owner Operator",                      _name_from_id_via_trip("drivers", "OwnerOperator.Id")),
    ("Location",                            None),                                   # UI real-time
    ("Truck",                               _name_from_id_via_trip("trucks", "Truck.Id")),
    ("Trailer",                             _name_from_id_via_trip("trailers", "Trailer.Id")),
    ("Customer Freight Charge",             "CustomerRate.Amount"),
    ("Contract Name",                       "ContractName"),
    ("Carrier Rate",                        _from_trip("TripValue.Amount")),
    ("Dispatcher",                          _name_from_id_via_trip("users", "DispatcherId")),
    ("Time Left",                           None),                                   # UI-only
    ("Location Update",                     None),                                   # UI-only
    ("Customer Payments",                   "TotalPaid.Amount"),
    ("Customer Payment Date",               "PaidAt"),
    ("Invoice Age",                         None),                                   # UI-computed
    ("Customer Due Date",                   _customer_invoice_field(["DueDate", "CustomerDueDate", "PaymentDueDate"])),
    ("Factoring Payments",                  _zero),                                  # cosmetic — always 0
    ("Factoring Fee",                       _zero),                                  # cosmetic — always 0
    ("Factoring Escrow",                    _zero),                                  # cosmetic — always 0
    ("Commissionable Amount",               "CommissionableAmount"),
    ("Last Check Call",                     None),                                   # UI real-time
    ("Notes",                               _notes),
    ("Dispatched Date",                     _from_trip("CarrierAssignedAt")),
    ("Invoiced Date",                       "InvoicedAt"),
    ("SMS",                                 "SMS"),
    ("Tender As",                           "InvoiceAs"),
    ("Gross Margin",                        _gross_margin),
    ("Carrier Advances",                    _driver1_rate_via_trip_or_zero("Advances")),
    ("Carrier Detention",                   _driver1_rate_via_trip_or_zero("Detention")),
    ("Carrier Lumper",                      _driver1_rate_via_trip_or_zero("Lumper")),
    ("Carrier Late Fee Reimbursement",      _zero),                                  # cosmetic — always 0
    ("Carrier Other Accessorials",          _driver1_rate_via_trip_or_zero("Other Accessorials")),
    ("Customer Detention",                  _zero_default("CustomerDetention")),
    ("Customer Lumpers",                    _zero_default("CustomerLumpers")),
    ("Customer Late Fees",                  _zero_default("CustomerLateFees")),
    ("Customer Other Accessorials",         "CustomerAccessorials.Amount"),
    ("Customer Linehaul",                   "Linehaul.Amount"),
    ("Customer Fuel Surcharge",             "FuelSurcharge.Amount"),
    ("Appointments Verified",               _appointments_verified),
    ("Carrier Invoice Number",              _carrier_invoice_field(["InvoiceNumber", "CarrierInvoiceNumber", "Number"])),
    ("Carrier Invoice Due Date",            _carrier_invoice_field(["DueDate", "CarrierInvoiceDueDate", "PaymentDueDate"])),
    ("Load Fleet",                          "Fleet.Name"),
    ("Driver 1 Fleet",                      _from_trip("Driver1.Fleet.Name")),
    ("Driver 2 Fleet",                      _from_trip("Driver2.Fleet.Name")),
    ("Truck Fleet",                         _from_trip("Truck.Fleet.Name")),
    ("Trailer Fleet",                       _from_trip("Trailer.Fleet.Name")),
    ("Carrier Factoring Company",           _factoring_company_load),
    ("Commodity",                           "Commodity"),
    ("Pickup Window Begin (FCFS)",          _stop_fcfs("first", "Begin")),
    ("Pickup Window End (FCFS)",            _stop_fcfs("first", "End")),
    ("Delivery Window Begin (FCFS)",        _stop_fcfs("last", "Begin")),
    ("Delivery Window End (FCFS)",          _stop_fcfs("last", "End")),
    ("Pickup Window (APPT)",                _stop_appt("first")),
    ("Delivery Window (APPT)",              _stop_appt("last")),
    ("Created",                             "CreatedAt"),
    ("Invoicing Method",                    _customer_field(["InvoicingMethod", "InvoiceMethod", "PreferredInvoicingMethod"])),
    ("Contract Lane Type",                  "ContractLaneType"),
]


# ===========================================================================
# TRIPS — 94 columns
# ===========================================================================
TRIPS_COLUMNS = [
    ("Carrier External Compliance Status",  None),
    ("Brokerage Status",                    _from_load("BrokerageStatus")),
    ("Date Imported",                       _from_load("CreatedAt")),
    ("Account Manager",                     _user_via_customer_via_load(["AccountManagerId", "AccountManager.Id"])),
    ("Carrier Sales Agent",                 None),
    ("Customer Service Representative",     _user_via_customer_via_load(["CustomerServiceRepresentativeId", "CSRId", "CustomerServiceRepId"])),
    ("Load Planner",                        _name_from_id_via_load("users", "CustomerLoadPlannerId")),
    ("Sales Manager",                       _user_via_customer_via_load(["SalesManagerId", "SalesManager.Id"])),
    ("Icons",                               None),
    ("Pickup Region",                       _from_load("PickupRegion")),
    ("Dropoff Region",                      _from_load("DropoffRegion")),
    ("Pickup Market",                       _from_load("PickupMarket")),
    ("Dropoff Market",                      _from_load("DropoffMarket")),
    ("Trip #",                              "TripNumber"),
    ("Order #",                             "OrderNumber"),
    ("Customer Revenue",                    _from_load("CustomerRate.Amount")),
    ("Driver Rate",                         "TripValue.Amount"),
    ("Reason Not Complete",                 _from_load("ReasonNotComplete")),
    ("Trip Status",                         "Status"),
    ("Load Status",                         _from_load("Status")),
    ("First Pick Status",                   "Stops.first.Status"),
    ("Last Drop Status",                    "Stops.last.Status"),
    ("Customer",                            _from_load("CustomerName")),
    ("Customer Freight Charge",             _from_load("CustomerRate.Amount")),
    ("Contract Name",                       _from_load("ContractName")),
    ("Posted Carrier Rate",                 _zero_default_via_load("PostedCarrierRate")),
    ("Stops",                               "Stops"),
    ("Loaded Miles",                        "LoadedMileage.Distance.Value"),
    ("Loaded Dispatch Mileage",             "LoadedMileage.Distance.Value"),
    ("Total Miles",                         "TotalMileage.Distance.Value"),
    ("Total Dispatch Mileage",              "TotalMileage.Distance.Value"),
    ("Empty Miles",                         "EmptyMileage.Distance.Value"),
    ("Empty Dispatch Mileage",              "EmptyMileage.Distance.Value"),
    ("Weight",                              _from_load("Weight")),
    ("Equipment",                           _first_equipment),
    ("First Stop",                          _first_stop_name),
    ("Pick City",                           "Stops.first.Address.City"),
    ("Pick State",                          "Stops.first.Address.State"),
    ("Scheduled Pickup",                    "PickupDate"),
    ("Pick Appt.",                          "Stops.first.AppointmentDate"),
    ("Last Stop",                           _last_stop_name),
    ("Drop City",                           "Stops.last.Address.City"),
    ("Drop State",                          "Stops.last.Address.State"),
    ("Scheduled Delivery",                  "DeliveryDate"),
    ("Drop Appt.",                          "Stops.last.AppointmentDate"),
    ("Carrier",                             _carrier_label_trip),
    ("Driver 1",                            _name_from_id("drivers", "Driver1.Id")),
    ("Driver 2",                            _name_from_id("drivers", "Driver2.Id")),
    ("Owner Operator",                      _name_from_id("drivers", "OwnerOperator.Id")),
    ("Truck",                               _name_from_id("trucks", "Truck.Id")),
    ("Trailer",                             _name_from_id("trailers", "Trailer.Id")),
    ("Carrier Rate",                        "TripValue.Amount"),
    ("Trip Value",                          "TripValue.Amount"),
    ("Location",                            None),                                   # UI real-time
    ("Next Stop",                           None),                                   # UI real-time
    ("ETA",                                 None),                                   # UI real-time
    ("Next Appointment",                    None),                                   # UI real-time
    ("Location Update",                     None),                                   # UI real-time
    ("Age",                                 None),                                   # UI-computed
    ("Created",                             _from_load("CreatedAt")),
    ("Office",                              _office_name_via_trip),
    ("Customer Sales Agent",                _name_from_id_via_load("users", "CustomerSalesAgentId")),
    ("Dispatcher",                          _name_from_id("users", "DispatcherId")),
    ("Factoring Payments",                  _zero),                                  # cosmetic — always 0
    ("Factoring Fee",                       _zero),                                  # cosmetic — always 0
    ("Factoring Escrow",                    _zero),                                  # cosmetic — always 0
    ("Dispatch Commissionable Amount",      _zero),                                  # cosmetic — always 0
    ("Last Check Call",                     None),                                   # UI real-time
    ("Notes",                               _notes_via_load),
    ("Carrier Invoice Due Date",            _carrier_invoice_field_via_load(["DueDate", "CarrierInvoiceDueDate", "PaymentDueDate"])),
    ("Dispatched Date",                     "CarrierAssignedAt"),
    ("Gross Margin",                        _gross_margin),
    ("Carrier Advances",                    _driver1_rate_or_zero("Advances")),
    ("SMS",                                 _from_load("SMS")),
    ("Tender As",                           "TenderAs"),
    ("Carrier Detention",                   _driver1_rate_or_zero("Detention")),
    ("Carrier Lumper",                      _driver1_rate_or_zero("Lumper")),
    ("Carrier Late Fee Reimbursement",      _zero),                                  # cosmetic — always 0
    ("Carrier Other Accessorials",          _driver1_rate_or_zero("Other Accessorials")),
    ("Customer Detention",                  _zero_default_via_load("CustomerDetention")),
    ("Customer Lumpers",                    _zero_default_via_load("CustomerLumpers")),
    ("Customer Late Fees",                  _zero_default_via_load("CustomerLateFees")),
    ("Customer Other Accessorials",         _from_load("CustomerAccessorials.Amount")),
    ("Customer Linehaul",                   _from_load("Linehaul.Amount")),
    ("Customer Fuel Surcharge",             _from_load("FuelSurcharge.Amount")),
    ("Appointments Verified",               _appointments_verified),
    ("Carrier Invoice Number",              _carrier_invoice_field_via_load(["InvoiceNumber", "CarrierInvoiceNumber", "Number"])),
    ("Load Fleet",                          _from_load("Fleet.Name")),
    ("Driver 1 Fleet",                      "Driver1.Fleet.Name"),
    ("Driver 2 Fleet",                      "Driver2.Fleet.Name"),
    ("Truck Fleet",                         "Truck.Fleet.Name"),
    ("Trailer Fleet",                       "Trailer.Fleet.Name"),
    ("Carrier Factoring Company",           _factoring_company_trip),
    ("Invoicing Method",                    _customer_field_via_load(["InvoicingMethod", "InvoiceMethod", "PreferredInvoicingMethod"])),
]


# ===========================================================================
# FUEL — 28 columns
# ===========================================================================
FUEL_COLUMNS = [
    ("Transaction Id",                      "TransactionId"),
    ("Card #",                              _fuel_card_field("CardNumber")),
    ("Deduct Transaction",                  _fuel_card_field("DeductFuel")),
    ("Paid / Stubbed",                      "PaidStubbed"),
    ("Transaction Date",                    "TransactionDate"),
    ("Transaction Time",                    "TransactionDate"),
    ("Invoice",                             "Invoice"),
    ("Location ID",                         "Location.Id"),
    ("Location Name",                       "Location.Name"),
    ("Address",                             "Location.Address"),
    ("City",                                "Location.City"),
    ("State",                               "Location.State"),
    ("Driver",                              "DriverName"),
    ("Truck",                               "TruckNumber"),
    ("Subsidiary",                          "SubsidiaryName"),
    ("Net Total",                           "FuelTotal.Amount"),
    ("Total Due",                           "Total.Amount"),
    ("Discount",                            "Discounts.Amount"),
    ("Transaction Fee",                     "Fees.Amount"),
    ("Currency",                            "Total.Currency"),
    ("Deduct From",                         _fuel_card_field("DeductFromName")),
    ("Retail PPU",                          "RetailPPU"),
    ("Discount PPU",                        "DiscountPPU"),
    ("Retail Cost",                         "RetailCost"),
    ("Quantity",                            "Quantity.Value"),
    ("Fuel Provider Description",           "Description"),
    ("Fuel Transaction Type",               "Category"),
    ("Source",                              "Source"),
]
