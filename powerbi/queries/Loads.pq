// =============================================================================
// Loads — Power Query M code  (v2 — full column set for XFreight Report)
//
// Produces the exact column names used by XFreight Report Connected.pbix.
// USAGE: Paste into Power Query Editor as Blank Query, rename to "Loads".
// REQUIRES: SharedHelpers, Trips, Drivers, Trucks, Users queries.
// NOTE: Trips query must be pasted FIRST (Loads joins to it for trip fields).
// =============================================================================
let
    // -- Fetch raw loads from Alvys ----------------------------------------
    RawLoads = SharedHelpers[FetchLoads](),

    AsTable = Table.FromList(RawLoads, Splitter.SplitByNothing(), {"Record"}),

    Expanded = Table.ExpandRecordColumn(
        AsTable, "Record",
        {
            "LoadNumber", "OrderNumber", "Status", "LoadType",
            "CustomerName", "CustomerRate", "CustomerMileage",
            "InvoiceAs", "TenderAs", "OfficeId", "Fleet",
            "ScheduledPickupAt", "ScheduledDeliveryAt",
            "PickedUpAt", "DeliveredAt", "CreatedAt", "InvoicedAt",
            "Stops", "Linehaul", "FuelSurcharge",
            "CustomerSalesAgentId", "CustomerLoadPlannerId", "DispatcherId",
            "PostedCarrierRate", "BrokerageStatus",
            "CustomerDetention", "CustomerLumpers", "CustomerLateFees",
            "Commodity", "ContractName", "ContractLaneType",
            "CommissionableAmount", "TotalPaid",
            "Notes"
        }
    ),

    // -- Helpers ----------------------------------------------------------
    AmountOf = (rec) =>
        if rec = null or not (rec is record) then null
        else Record.FieldOrDefault(rec, "Amount", null),

    DistanceOf = (rec) =>
        if rec = null or not (rec is record) then null
        else
            let d = Record.FieldOrDefault(rec, "Distance", null)
            in if d is record then Record.FieldOrDefault(d, "Value", null) else null,

    StopAddressField = (stops, which as text, field as text) =>
        if stops = null or not (stops is list) or List.IsEmpty(stops) then null
        else
            let
                stop = if which = "first" then stops{0}
                       else stops{List.Count(stops) - 1},
                addr = if stop is record then Record.FieldOrDefault(stop, "Address", null)
                       else null
            in if addr is record then Record.FieldOrDefault(addr, field, null) else null,

    FirstStopName = (stops) =>
        if stops = null or not (stops is list) or List.IsEmpty(stops) then null
        else
            let stop = stops{0}
            in if stop is record then
                let nm = Record.FieldOrDefault(stop, "Name", null)
                in if nm <> null then nm
                   else
                       let a = Record.FieldOrDefault(stop, "Address", null)
                       in if a is record then
                              Text.Trim(
                                  (if Record.FieldOrDefault(a, "City", null) <> null
                                   then Record.FieldOrDefault(a, "City", "") else "") &
                                  ", " &
                                  (if Record.FieldOrDefault(a, "State", null) <> null
                                   then Record.FieldOrDefault(a, "State", "") else ""))
                          else null
               else null,

    LastStopName = (stops) =>
        if stops = null or not (stops is list) or List.IsEmpty(stops) then null
        else
            let stop = stops{List.Count(stops) - 1}
            in if stop is record then
                let nm = Record.FieldOrDefault(stop, "Name", null)
                in if nm <> null then nm
                   else
                       let a = Record.FieldOrDefault(stop, "Address", null)
                       in if a is record then
                              Text.Trim(
                                  (if Record.FieldOrDefault(a, "City", null) <> null
                                   then Record.FieldOrDefault(a, "City", "") else "") &
                                  ", " &
                                  (if Record.FieldOrDefault(a, "State", null) <> null
                                   then Record.FieldOrDefault(a, "State", "") else ""))
                          else null
               else null,

    OfficeMap = (raw as nullable text) as nullable text =>
        if raw = null then null
        else if raw = "X-LINX INC" or raw = "X-LINX INC (BROKERAGE)"
             or raw = "XLINX" or raw = "X-LINX" then "X-Linx, Inc."
        else if raw = "X-TRUX INC" or raw = "XTRUX" or raw = "X-TRUX" then "X-Trux, Inc"
        else if raw = "XFREIGHT INC" or raw = "XFREIGHT" then "XFreight"
        else raw,

    // -- Core computed columns from the load itself -----------------------
    WithPickCity  = Table.AddColumn(Expanded, "Pick City",
        each StopAddressField([Stops], "first", "City"), type text),
    WithPickState = Table.AddColumn(WithPickCity, "Pick State",
        each StopAddressField([Stops], "first", "State"), type text),
    WithDropCity  = Table.AddColumn(WithPickState, "Drop City",
        each StopAddressField([Stops], "last", "City"), type text),
    WithDropState = Table.AddColumn(WithDropCity, "Drop State",
        each StopAddressField([Stops], "last", "State"), type text),

    WithFirstStop = Table.AddColumn(WithDropState, "First Stop",
        each FirstStopName([Stops]), type text),
    WithLastStop  = Table.AddColumn(WithFirstStop, "Last Stop",
        each LastStopName([Stops]), type text),

    WithCustRev   = Table.AddColumn(WithLastStop, "Customer Revenue",
        each AmountOf([CustomerRate]), type number),
    WithCustMiles = Table.AddColumn(WithCustRev, "Customer Miles",
        each DistanceOf([CustomerMileage]), type number),
    WithCustLine  = Table.AddColumn(WithCustMiles, "Customer Linehaul",
        each AmountOf([Linehaul]), type number),
    WithCustFSC   = Table.AddColumn(WithCustLine, "Customer Fuel Surcharge",
        each AmountOf([FuelSurcharge]), type number),
    WithPostedCR  = Table.AddColumn(WithCustFSC, "Posted Carrier Rate",
        each if [PostedCarrierRate] = null then 0 else [PostedCarrierRate], type number),

    WithOffice    = Table.AddColumn(WithPostedCR, "Office",
        each OfficeMap([InvoiceAs]), type text),

    // -- Join to Trips for trip-level data --------------------------------
    TripsForJoin  = Table.SelectColumns(Trips,
        {"Load #", "Driver Rate", "Loaded Dispatch Mileage",
         "Empty Dispatch Mileage", "Total Dispatch Mileage",
         "Carrier", "Carrier Rate", "Dispatched Date",
         "Driver 1", "Driver 2", "Driver 1 Fleet", "Truck", "Trailer",
         "Trip Value", "Gross Margin"},
        MissingField.Ignore),

    WithTripJoin  = Table.NestedJoin(WithOffice, {"LoadNumber"},
        TripsForJoin, {"Load #"}, "_trip", JoinKind.LeftOuter),
    WithTripFirst = Table.AddColumn(WithTripJoin, "_trip_rec",
        each if Table.IsEmpty([_trip]) then null else Table.First([_trip])),

    TripField = (row as record, col as text) =>
        if row[_trip_rec] = null then null
        else Record.FieldOrDefault(row[_trip_rec], col, null),

    WithDriverRate   = Table.AddColumn(WithTripFirst, "Driver Rate",
        each let v = TripField(_, "Driver Rate") in if v = null then 0 else v, type number),
    WithLoadedMi     = Table.AddColumn(WithDriverRate, "Loaded Dispatch Mileage",
        each TripField(_, "Loaded Dispatch Mileage"), type number),
    WithEmptyMi      = Table.AddColumn(WithLoadedMi, "Empty Dispatch Mileage",
        each TripField(_, "Empty Dispatch Mileage"), type number),
    WithTotalMi      = Table.AddColumn(WithEmptyMi, "Total Dispatch Mileage",
        each TripField(_, "Total Dispatch Mileage"), type number),
    WithCarrier      = Table.AddColumn(WithTotalMi, "Carrier",
        each TripField(_, "Carrier"), type text),
    WithCarrierRate  = Table.AddColumn(WithCarrier, "Carrier Rate",
        each TripField(_, "Carrier Rate"), type number),
    WithDispDate     = Table.AddColumn(WithCarrierRate, "Dispatched Date",
        each TripField(_, "Dispatched Date"), type datetime),
    WithDriver1      = Table.AddColumn(WithDispDate, "Driver 1",
        each TripField(_, "Driver 1"), type text),
    WithDriver2      = Table.AddColumn(WithDriver1, "Driver 2",
        each TripField(_, "Driver 2"), type text),
    WithD1Fleet      = Table.AddColumn(WithDriver2, "Driver 1 Fleet",
        each TripField(_, "Driver 1 Fleet"), type text),
    WithTruck        = Table.AddColumn(WithD1Fleet, "Truck",
        each TripField(_, "Truck"), type text),
    WithTrailer      = Table.AddColumn(WithTruck, "Trailer",
        each TripField(_, "Trailer"), type text),

    // -- Gross Margin (Customer Revenue - Driver Rate) ---------------------
    WithGrossMargin  = Table.AddColumn(WithTrailer, "Gross Margin",
        each [Customer Revenue] - [Driver Rate], type number),

    // -- Resolve user names via Users lookup ------------------------------
    UsersForCSA  = Table.SelectColumns(Users, {"Id", "User Name"}, MissingField.Ignore),
    UsersForLP   = Table.SelectColumns(Users, {"Id", "User Name"}, MissingField.Ignore),

    WithCSAJoin  = Table.NestedJoin(WithGrossMargin, {"CustomerSalesAgentId"},
        UsersForCSA, {"Id"}, "_csa", JoinKind.LeftOuter),
    WithCSAFirst = Table.AddColumn(WithCSAJoin, "_csa_rec",
        each if Table.IsEmpty([_csa]) then null else Table.First([_csa])),
    WithCSA      = Table.AddColumn(WithCSAFirst, "Customer Sales Agent",
        each if [_csa_rec] = null then null
             else Record.FieldOrDefault([_csa_rec], "User Name", null), type text),

    WithLPJoin   = Table.NestedJoin(WithCSA, {"CustomerLoadPlannerId"},
        UsersForLP, {"Id"}, "_lp", JoinKind.LeftOuter),
    WithLPFirst  = Table.AddColumn(WithLPJoin, "_lp_rec",
        each if Table.IsEmpty([_lp]) then null else Table.First([_lp])),
    WithLP       = Table.AddColumn(WithLPFirst, "Load Planner",
        each if [_lp_rec] = null then null
             else Record.FieldOrDefault([_lp_rec], "User Name", null), type text),

    // -- Rename core load fields ------------------------------------------
    Renamed = Table.RenameColumns(WithLP, {
        {"LoadNumber",          "Load #"},
        {"OrderNumber",         "Order #"},
        {"Status",              "Load Status"},
        {"LoadType",            "Load Type"},
        {"CustomerName",        "Customer"},
        {"InvoiceAs",           "Invoice As"},
        {"TenderAs",            "Tender As"},
        {"ScheduledPickupAt",   "Scheduled Pickup"},
        {"ScheduledDeliveryAt", "Scheduled Delivery"},
        {"InvoicedAt",          "Invoiced Date"},
        {"CommissionableAmount","Commissionable Amount"},
        {"ContractName",        "Contract Name"},
        {"ContractLaneType",    "Contract Lane Type"},
        {"Commodity",           "Commodity"},
        {"BrokerageStatus",     "Brokerage Status"}
    }, MissingField.Ignore),

    // Load Lane = "Pick City, PS → Drop City, DS"
    WithLane = Table.AddColumn(Renamed, "Load Lane",
        each
            let
                p = (if [Pick City] <> null then [Pick City] else "") &
                    (if [Pick State] <> null then ", " & [Pick State] else ""),
                d = (if [Drop City] <> null then [Drop City] else "") &
                    (if [Drop State] <> null then ", " & [Drop State] else "")
            in if p = "" and d = "" then null else p & " → " & d,
        type text),

    // -- Drop helper / raw nested columns ---------------------------------
    Cleaned = Table.RemoveColumns(Renamed,
        {"_trip", "_trip_rec", "_csa", "_csa_rec", "_lp", "_lp_rec",
         "Stops", "CustomerRate", "CustomerMileage", "Linehaul", "FuelSurcharge",
         "PostedCarrierRate", "OfficeId", "Fleet",
         "PickedUpAt", "DeliveredAt", "CreatedAt",
         "CustomerSalesAgentId", "CustomerLoadPlannerId", "DispatcherId",
         "CustomerDetention", "CustomerLumpers", "CustomerLateFees",
         "TotalPaid"},
        MissingField.Ignore),

    // -- Final type pass --------------------------------------------------
    Typed = Table.TransformColumnTypes(Cleaned, {
        {"Load #",                    type text},
        {"Order #",                   type text},
        {"Load Status",               type text},
        {"Load Type",                 type text},
        {"Customer",                  type text},
        {"Customer Revenue",          type number},
        {"Customer Miles",            type number},
        {"Customer Linehaul",         type number},
        {"Customer Fuel Surcharge",   type number},
        {"Invoice As",                type text},
        {"Tender As",                 type text},
        {"Office",                    type text},
        {"Scheduled Pickup",          type datetime},
        {"Scheduled Delivery",        type datetime},
        {"Dispatched Date",           type datetime},
        {"Pick City",                 type text},
        {"Pick State",                type text},
        {"Drop City",                 type text},
        {"Drop State",                type text},
        {"First Stop",                type text},
        {"Last Stop",                 type text},
        {"Load Lane",                 type text},
        {"Driver Rate",               type number},
        {"Gross Margin",              type number},
        {"Loaded Dispatch Mileage",   type number},
        {"Empty Dispatch Mileage",    type number},
        {"Total Dispatch Mileage",    type number},
        {"Carrier",                   type text},
        {"Carrier Rate",              type number},
        {"Driver 1",                  type text},
        {"Driver 2",                  type text},
        {"Driver 1 Fleet",            type text},
        {"Truck",                     type text},
        {"Trailer",                   type text},
        {"Customer Sales Agent",      type text},
        {"Load Planner",              type text},
        {"Brokerage Status",          type text},
        {"Posted Carrier Rate",       type number},
        {"Contract Name",             type text},
        {"Load Lane",                 type text},
        {"Commodity",                 type text},
        {"Notes",                     type text}
    }, MissingField.Ignore)
in
    Typed
