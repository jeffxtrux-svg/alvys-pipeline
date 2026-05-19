// =============================================================================
// Loads — Power Query M code, replaces the Excel-driven Loads query.
//
// USAGE: Paste into Power Query Editor as a Blank Query. Rename to "Loads"
// (left panel). Requires: SharedHelpers query, AlvysClientId/Secret/StartDate
// parameters, and the Trips query (for trip-level joins).
//
// Phase 1 scope: 28 columns referenced by report visuals + a handful of
// essentials. Add more columns to ColumnTransforms as you need them.
// =============================================================================
let
    // -- Fetch raw loads from Alvys ----------------------------------------
    RawLoads = SharedHelpers[FetchLoads](),

    // -- Convert list-of-records to a single table (preserves nested fields)
    AsTable = Table.FromList(
        RawLoads,
        Splitter.SplitByNothing(),
        {"Record"}
    ),

    Expanded = Table.ExpandRecordColumn(
        AsTable, "Record",
        // The fields we'll pull from each load record. Listed here as the
        // RAW Alvys field names. We rename + reshape them in the next step.
        {
            "LoadNumber", "OrderNumber", "Status", "LoadType",
            "CustomerName", "CustomerRate", "CustomerMileage",
            "InvoiceAs", "TenderAs", "OfficeId",
            "ScheduledPickupAt", "ScheduledDeliveryAt",
            "PickedUpAt", "DeliveredAt", "CreatedAt", "UpdatedAt",
            "Stops",
            "CustomerSalesAgentId", "CustomerLoadPlannerId",
            "PostedCarrierRate", "BrokerageStatus"
        }
    ),

    // -- Helper: safely get a numeric Amount from {Amount, Currency} blob
    AmountOf = (rec) =>
        if rec = null then null
        else if rec is record then Record.FieldOrDefault(rec, "Amount", null)
        else null,

    // -- Helper: safely get distance from {Distance: {Value, UnitOfMeasure}, ...}
    DistanceOf = (rec) =>
        if rec = null or not (rec is record) then null
        else
            let
                d = Record.FieldOrDefault(rec, "Distance", null)
            in
                if d is record then Record.FieldOrDefault(d, "Value", null)
                else null,

    // -- Helper: first/last stop's address field (City, State, etc.)
    StopAddressField = (stops, which as text, field as text) =>
        if stops = null or not (stops is list) or List.IsEmpty(stops) then null
        else
            let
                stop = if which = "first" then stops{0} else stops{List.Count(stops) - 1},
                addr = if stop is record then Record.FieldOrDefault(stop, "Address", null) else null
            in
                if addr is record then Record.FieldOrDefault(addr, field, null) else null,

    // -- Build the final table with cleanly named columns ------------------
    Shaped = Table.AddColumn(Expanded, "Pick City",
                each StopAddressField([Stops], "first", "City"), type text),
    Shaped2 = Table.AddColumn(Shaped, "Pick State",
                each StopAddressField([Stops], "first", "State"), type text),
    Shaped3 = Table.AddColumn(Shaped2, "Drop City",
                each StopAddressField([Stops], "last", "City"), type text),
    Shaped4 = Table.AddColumn(Shaped3, "Drop State",
                each StopAddressField([Stops], "last", "State"), type text),
    Shaped5 = Table.AddColumn(Shaped4, "Customer Revenue",
                each AmountOf([CustomerRate]), type number),
    Shaped6 = Table.AddColumn(Shaped5, "Customer Miles",
                each DistanceOf([CustomerMileage]), type number),
    Shaped7 = Table.AddColumn(Shaped6, "Posted Carrier Rate",
                each if [PostedCarrierRate] = null then 0 else [PostedCarrierRate],
                type number),

    // -- Join to Trips for trip-level data (Driver Rate, mileage, etc.) ----
    // Trips query is keyed by LoadNumber so we can match.
    WithTripJoin = Table.NestedJoin(
        Shaped7, {"LoadNumber"},
        Trips, {"LoadNumber"},
        "_trip", JoinKind.LeftOuter
    ),

    // -- Pull selected fields from the joined trip
    WithTripFields = Table.AddColumn(WithTripJoin, "_trip_first",
        each if Table.IsEmpty([_trip]) then null else Table.First([_trip]),
        type any),

    // -- Trip-derived columns -----------------------------------------------
    Loads1 = Table.AddColumn(WithTripFields, "Driver Rate",
        each if [_trip_first] = null then 0
             else Record.FieldOrDefault([_trip_first], "Driver Rate", 0),
        type number),

    Loads2 = Table.AddColumn(Loads1, "Loaded Dispatch Mileage",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Loaded Mileage", null),
        type number),

    Loads3 = Table.AddColumn(Loads2, "Empty Dispatch Mileage",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Empty Mileage", null),
        type number),

    Loads4 = Table.AddColumn(Loads3, "Total Dispatch Mileage",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Total Mileage", null),
        type number),

    Loads5 = Table.AddColumn(Loads4, "Empty Miles",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Empty Mileage", null),
        type number),

    Loads6 = Table.AddColumn(Loads5, "Driver 1",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Driver 1 Name", null),
        type text),

    Loads7 = Table.AddColumn(Loads6, "Driver 2",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Driver 2 Name", null),
        type text),

    Loads8 = Table.AddColumn(Loads7, "Truck",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Truck Number", null),
        type text),

    Loads9 = Table.AddColumn(Loads8, "Trailer",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Trailer Number", null),
        type text),

    Loads10 = Table.AddColumn(Loads9, "Carrier",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Carrier Name", null),
        type text),

    Loads11 = Table.AddColumn(Loads10, "Carrier Rate",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Carrier Rate", null),
        type number),

    Loads12 = Table.AddColumn(Loads11, "Dispatched Date",
        each if [_trip_first] = null then null
             else Record.FieldOrDefault([_trip_first], "Dispatched Date Raw", null),
        type datetime),

    // -- Office name mapping (InvoiceAs raw → display name) ----------------
    OfficeMap = (raw as nullable text) as nullable text =>
        if raw = null then null
        else if raw = "X-LINX INC" or raw = "X-LINX INC (BROKERAGE)" then "X-Linx, Inc."
        else if raw = "X-TRUX INC" then "X-Trux, Inc"
        else if raw = "XFREIGHT INC" or raw = "XFREIGHT" then "XFreight"
        else raw,

    Loads13 = Table.AddColumn(Loads12, "Office",
        each OfficeMap([InvoiceAs]), type text),

    // -- Final rename + select -----------------------------------------------
    Renamed = Table.RenameColumns(Loads13, {
        {"LoadNumber",          "Load #"},
        {"OrderNumber",         "Order #"},
        {"Status",              "Load Status"},
        {"LoadType",            "Load Type"},
        {"CustomerName",        "Customer"},
        {"InvoiceAs",           "Invoice As"},
        {"TenderAs",            "Tender As"},
        {"ScheduledPickupAt",   "Scheduled Pickup"},
        {"ScheduledDeliveryAt", "Scheduled Delivery"},
        {"CustomerSalesAgentId","Customer Sales Agent"},  // TODO: resolve to name via users lookup
        {"CustomerLoadPlannerId","Load Planner"}           // TODO: resolve to name
    }, MissingField.Ignore),

    // -- Gross Margin (computed) -------------------------------------------
    WithMargin = Table.AddColumn(Renamed, "Gross Margin",
        each (if [Customer Revenue] = null then 0 else [Customer Revenue])
           - (if [Driver Rate]     = null then 0 else [Driver Rate]),
        type number),

    // -- Drop helper columns ------------------------------------------------
    Cleaned = Table.RemoveColumns(WithMargin,
        {"_trip", "_trip_first", "Stops", "CustomerRate", "CustomerMileage",
         "PostedCarrierRate", "OfficeId", "PickedUpAt", "DeliveredAt",
         "CreatedAt", "UpdatedAt", "BrokerageStatus"},
        MissingField.Ignore),

    // -- Final typed table — explicit types so Power BI doesn't have to guess
    Typed = Table.TransformColumnTypes(Cleaned, {
        {"Load #",                type text},
        {"Order #",               type text},
        {"Load Status",           type text},
        {"Load Type",             type text},
        {"Customer",              type text},
        {"Customer Revenue",      type number},
        {"Customer Miles",        type number},
        {"Invoice As",            type text},
        {"Tender As",             type text},
        {"Office",                type text},
        {"Scheduled Pickup",      type datetime},
        {"Scheduled Delivery",    type datetime},
        {"Pick City",             type text},
        {"Pick State",            type text},
        {"Drop City",             type text},
        {"Drop State",            type text},
        {"Driver Rate",           type number},
        {"Gross Margin",          type number},
        {"Loaded Dispatch Mileage", type number},
        {"Empty Dispatch Mileage",  type number},
        {"Total Dispatch Mileage",  type number},
        {"Empty Miles",           type number},
        {"Driver 1",              type text},
        {"Driver 2",              type text},
        {"Truck",                 type text},
        {"Trailer",               type text},
        {"Carrier",               type text},
        {"Carrier Rate",          type number},
        {"Dispatched Date",       type datetime},
        {"Posted Carrier Rate",   type number},
        {"Customer Sales Agent",  type text},
        {"Load Planner",          type text}
    }, MissingField.Ignore)
in
    Typed
