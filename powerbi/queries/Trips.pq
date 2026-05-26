// =============================================================================
// Trips — Power Query M code  (v2 — full column set for XFreight Report)
//
// Produces the exact column names used by XFreight Report Connected.pbix.
// USAGE: Paste into Power Query Editor as Blank Query, rename to "Trips".
// REQUIRES: SharedHelpers, Loads, Drivers, Trucks, Users queries.
// =============================================================================
let
    // -- Fetch raw trips ---------------------------------------------------
    RawTrips = SharedHelpers[FetchTrips](),

    AsTable = Table.FromList(RawTrips, Splitter.SplitByNothing(), {"Record"}),

    Expanded = Table.ExpandRecordColumn(
        AsTable, "Record",
        {
            "TripNumber", "LoadNumber", "OrderNumber", "Status",
            "TenderAs", "TenderAsSubsidiaryType",
            "PickupDate", "DeliveryDate", "PickedUpAt", "DeliveredAt",
            "CarrierAssignedAt", "ReleasedAt",
            "TotalMileage", "EmptyMileage", "LoadedMileage",
            "TripValue", "Driver1", "Driver2", "OwnerOperator",
            "Truck", "Trailer", "Carrier", "Stops", "DispatcherId",
            "UpdatedAt"
        }
    ),

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------
    DistanceOf = (rec) =>
        if rec = null or not (rec is record) then null
        else
            let d = Record.FieldOrDefault(rec, "Distance", null)
            in if d is record then Record.FieldOrDefault(d, "Value", null) else null,

    AmountOf = (rec) =>
        if rec = null or not (rec is record) then null
        else Record.FieldOrDefault(rec, "Amount", null),

    Field = (r, keys as list) =>
        if r = null or not (r is record) then null
        else List.First(List.RemoveNulls(
                List.Transform(keys, each Record.FieldOrDefault(r, _, null))), null),

    StopAddressField = (stops, which as text, field as text) =>
        if stops = null or not (stops is list) or List.IsEmpty(stops) then null
        else
            let
                stop = if which = "first" then stops{0}
                       else stops{List.Count(stops) - 1},
                addr = if stop is record then Record.FieldOrDefault(stop, "Address", null)
                       else null
            in if addr is record then Record.FieldOrDefault(addr, field, null) else null,

    // -----------------------------------------------------------------------
    // Driver Rate (RatesV2 with legacy Rates[] fallback)
    // -----------------------------------------------------------------------
    SingleTierRate = (tierObj) =>
        if tierObj = null or not (tierObj is record) then 0
        else
            let
                tiers  = Field(tierObj, {"tiers", "Tiers"}),
                first  = if tiers is list and not List.IsEmpty(tiers)
                             and tiers{0} is record
                         then Field(tiers{0}, {"rate", "Rate"}) else null,
                flat   = if first <> null then first else Field(tierObj, {"rate", "Rate"})
            in if flat is number then flat else 0,

    LegacyRateForType = (ratesList, rateType as text) =>
        if not (ratesList is list) then 0
        else
            let
                match = List.First(List.Select(ratesList, each
                    _ is record and
                    Record.FieldOrDefault(_, "RateType", "") = rateType), null),
                rate = if match <> null then Record.FieldOrDefault(match, "Rate", 0) else 0
            in if rate is number then rate else 0,

    CalcDriverRate = (trip as record) =>
        let
            d1 = Record.FieldOrDefault(trip, "Driver1", null),
            loadedMi = let v = DistanceOf(Record.FieldOrDefault(trip, "LoadedMileage", null))
                       in if v is number then v else 0,
            emptyMi  = let v = DistanceOf(Record.FieldOrDefault(trip, "EmptyMileage", null))
                       in if v is number then v else 0,
            ratesV2  = if d1 is record then Field(d1, {"RatesV2", "ratesV2"}) else null,
            v2Pay =
                if ratesV2 is list and not List.IsEmpty(ratesV2) then
                    let
                        lSum = List.Sum(List.Transform(ratesV2, each
                                    SingleTierRate(Field(_, {"loadedMilesRate", "LoadedMilesRate"})))),
                        eSum = List.Sum(List.Transform(ratesV2, each
                                    SingleTierRate(Field(_, {"emptyMilesRate", "EmptyMilesRate"}))))
                    in (lSum * loadedMi) + (eSum * emptyMi)
                else 0,
            legacyPay =
                if v2Pay > 0 then 0
                else
                    let
                        rates = if d1 is record then
                                    Record.FieldOrDefault(d1, "Rates", {}) else {},
                        lr = LegacyRateForType(rates, "Loaded Miles"),
                        er = LegacyRateForType(rates, "Empty Miles")
                    in (lr * loadedMi) + (er * emptyMi)
        in v2Pay + legacyPay,

    // -----------------------------------------------------------------------
    // Build columns
    // -----------------------------------------------------------------------
    // Mileage columns (renamed to match Connected report)
    WithLoadedMi = Table.AddColumn(Expanded, "Loaded Dispatch Mileage",
        each DistanceOf([LoadedMileage]), type number),
    WithEmptyMi  = Table.AddColumn(WithLoadedMi, "Empty Dispatch Mileage",
        each DistanceOf([EmptyMileage]), type number),
    WithTotalMi  = Table.AddColumn(WithEmptyMi, "Total Dispatch Mileage",
        each DistanceOf([TotalMileage]), type number),

    WithDriverRate = Table.AddColumn(WithTotalMi, "Driver Rate",
        each CalcDriverRate(_), type number),
    WithTripValue  = Table.AddColumn(WithDriverRate, "Trip Value",
        each AmountOf([TripValue]), type number),

    // Carrier columns
    WithCarrierRate = Table.AddColumn(WithTripValue, "Carrier Rate",
        each if [Carrier] = null or not ([Carrier] is record) then null
             else AmountOf(Record.FieldOrDefault([Carrier], "Rate", null)),
        type number),
    WithCarrierName = Table.AddColumn(WithCarrierRate, "Carrier",
        each if [Carrier] = null or not ([Carrier] is record) then null
             else Record.FieldOrDefault([Carrier], "Name",
                  Record.FieldOrDefault([Carrier], "ExternalName", null)),
        type text),

    // Driver IDs & Fleet
    WithD1Id = Table.AddColumn(WithCarrierName, "_Driver1Id",
        each if [Driver1] is record then Record.FieldOrDefault([Driver1], "Id", null)
             else null, type text),
    WithD1Fleet = Table.AddColumn(WithD1Id, "Driver 1 Fleet",
        each if [Driver1] is record then
                let f = Record.FieldOrDefault([Driver1], "Fleet", null)
                in if f is record then Record.FieldOrDefault(f, "Name", null) else null
             else null, type text),

    WithD2Id = Table.AddColumn(WithD1Fleet, "_Driver2Id",
        each if [Driver2] is record then Record.FieldOrDefault([Driver2], "Id", null)
             else null, type text),

    // Truck & Trailer IDs
    WithTruckId = Table.AddColumn(WithD2Id, "_TruckId",
        each if [Truck] is record then
                Record.FieldOrDefault([Truck], "Id", null)
             else null, type text),
    WithTruckNum = Table.AddColumn(WithTruckId, "_TruckNumber",
        each if [Truck] is record then
                Record.FieldOrDefault([Truck], "Number",
                Record.FieldOrDefault([Truck], "Id", null))
             else null, type text),

    WithTrailerNum = Table.AddColumn(WithTruckNum, "Trailer",
        each if [Trailer] is record then
                Record.FieldOrDefault([Trailer], "Number",
                Record.FieldOrDefault([Trailer], "Id", null))
             else null, type text),

    // Stop-level address columns
    WithPickCity  = Table.AddColumn(WithTrailerNum, "Pick City",
        each StopAddressField([Stops], "first", "City"), type text),
    WithPickState = Table.AddColumn(WithPickCity, "Pick State",
        each StopAddressField([Stops], "first", "State"), type text),
    WithDropCity  = Table.AddColumn(WithPickState, "Drop City",
        each StopAddressField([Stops], "last", "City"), type text),
    WithDropState = Table.AddColumn(WithDropCity, "Drop State",
        each StopAddressField([Stops], "last", "State"), type text),

    // -----------------------------------------------------------------------
    // Rename core fields
    // -----------------------------------------------------------------------
    Renamed = Table.RenameColumns(WithDropState, {
        {"TripNumber",       "Trip #"},
        {"LoadNumber",       "Load #"},
        {"OrderNumber",      "Order #"},
        {"Status",           "Trip Status"},
        {"TenderAs",         "Tender As"},
        {"PickupDate",       "Scheduled Pickup"},
        {"DeliveryDate",     "Scheduled Delivery"},
        {"CarrierAssignedAt","Dispatched Date"}
    }, MissingField.Ignore),

    // Add Scheduled Pickup Date alias (some pages use both names)
    WithPickupDate = Table.AddColumn(Renamed, "Scheduled Pickup Date",
        each [Scheduled Pickup], type datetime),

    // -----------------------------------------------------------------------
    // Join Drivers lookup → "Driver 1", "Driver 2"
    // -----------------------------------------------------------------------
    WithD1Name = Table.NestedJoin(WithPickupDate, {"_Driver1Id"}, Drivers, {"Id"},
        "_d1", JoinKind.LeftOuter),
    WithD1First = Table.AddColumn(WithD1Name, "_d1_rec",
        each if Table.IsEmpty([_d1]) then null else Table.First([_d1])),
    WithDriver1 = Table.AddColumn(WithD1First, "Driver 1",
        each if [_d1_rec] = null then null
             else Record.FieldOrDefault([_d1_rec], "Driver Name", null), type text),

    WithD2Name = Table.NestedJoin(WithDriver1, {"_Driver2Id"}, Drivers, {"Id"},
        "_d2", JoinKind.LeftOuter),
    WithD2First = Table.AddColumn(WithD2Name, "_d2_rec",
        each if Table.IsEmpty([_d2]) then null else Table.First([_d2])),
    WithDriver2 = Table.AddColumn(WithD2First, "Driver 2",
        each if [_d2_rec] = null then null
             else Record.FieldOrDefault([_d2_rec], "Driver Name", null), type text),

    // -----------------------------------------------------------------------
    // Join Trucks lookup → "Truck"
    // -----------------------------------------------------------------------
    WithTruckJoin = Table.NestedJoin(WithDriver2, {"_TruckId"}, Trucks, {"Id"},
        "_tk", JoinKind.LeftOuter),
    WithTruckFirst = Table.AddColumn(WithTruckJoin, "_tk_rec",
        each if Table.IsEmpty([_tk]) then null else Table.First([_tk])),
    WithTruckLabel = Table.AddColumn(WithTruckFirst, "Truck",
        each
            if [_tk_rec] <> null then
                Record.FieldOrDefault([_tk_rec], "Truck Label", null)
            // Fall back to the raw Truck.Number we extracted earlier
            else [_TruckNumber],
        type text),

    // -----------------------------------------------------------------------
    // Join Loads (left-outer) → Customer, Customer Revenue, Office, Load Status, Notes
    // -----------------------------------------------------------------------
    LoadsForJoin = Table.SelectColumns(Loads,
        {"Load #", "Customer", "Customer Revenue", "Office", "Load Status", "Notes"},
        MissingField.Ignore),

    WithLoadsJoin = Table.NestedJoin(WithTruckLabel, {"Load #"}, LoadsForJoin, {"Load #"},
        "_ld", JoinKind.LeftOuter),
    WithLdFirst = Table.AddColumn(WithLoadsJoin, "_ld_rec",
        each if Table.IsEmpty([_ld]) then null else Table.First([_ld])),

    WithCustomer = Table.AddColumn(WithLdFirst, "Customer",
        each if [_ld_rec] = null then null
             else Record.FieldOrDefault([_ld_rec], "Customer", null), type text),
    WithCustRev  = Table.AddColumn(WithCustomer, "Customer Revenue",
        each if [_ld_rec] = null then null
             else Record.FieldOrDefault([_ld_rec], "Customer Revenue", null), type number),
    WithOffice   = Table.AddColumn(WithCustRev, "Office",
        each if [_ld_rec] = null then null
             else Record.FieldOrDefault([_ld_rec], "Office", null), type text),
    WithLoadStat = Table.AddColumn(WithOffice, "Load Status",
        each if [_ld_rec] = null then null
             else Record.FieldOrDefault([_ld_rec], "Load Status", null), type text),
    WithNotes    = Table.AddColumn(WithLoadStat, "Notes",
        each if [_ld_rec] = null then null
             else Record.FieldOrDefault([_ld_rec], "Notes", null), type text),

    // Gross Margin on Trip level
    WithGrossMargin = Table.AddColumn(WithNotes, "Gross Margin",
        each
            let
                rev  = [Customer Revenue],
                cost = [Driver Rate]
            in if rev = null or cost = null then null else rev - cost,
        type number),

    // -----------------------------------------------------------------------
    // Clean up helper columns
    // -----------------------------------------------------------------------
    Cleaned = Table.RemoveColumns(WithGrossMargin,
        {"LoadedMileage", "EmptyMileage", "TotalMileage", "TripValue",
         "Driver1", "Driver2", "OwnerOperator", "Truck", "Trailer", "Carrier",
         "Stops", "PickedUpAt", "DeliveredAt", "ReleasedAt", "DispatcherId",
         "UpdatedAt", "TenderAsSubsidiaryType",
         "_Driver1Id", "_Driver2Id", "_TruckId", "_TruckNumber",
         "_d1", "_d1_rec", "_d2", "_d2_rec", "_tk", "_tk_rec",
         "_ld", "_ld_rec"},
        MissingField.Ignore),

    // -----------------------------------------------------------------------
    // Final type pass
    // -----------------------------------------------------------------------
    Typed = Table.TransformColumnTypes(Cleaned, {
        {"Trip #",                    type text},
        {"Load #",                    type text},
        {"Order #",                   type text},
        {"Trip Status",               type text},
        {"Load Status",               type text},
        {"Tender As",                 type text},
        {"Scheduled Pickup",          type datetime},
        {"Scheduled Pickup Date",     type datetime},
        {"Scheduled Delivery",        type datetime},
        {"Dispatched Date",           type datetime},
        {"Driver Rate",               type number},
        {"Trip Value",                type number},
        {"Loaded Dispatch Mileage",   type number},
        {"Empty Dispatch Mileage",    type number},
        {"Total Dispatch Mileage",    type number},
        {"Carrier Rate",              type number},
        {"Customer Revenue",          type number},
        {"Gross Margin",              type number},
        {"Carrier",                   type text},
        {"Driver 1",                  type text},
        {"Driver 2",                  type text},
        {"Driver 1 Fleet",            type text},
        {"Truck",                     type text},
        {"Trailer",                   type text},
        {"Customer",                  type text},
        {"Office",                    type text},
        {"Notes",                     type text},
        {"Pick City",                 type text},
        {"Pick State",                type text},
        {"Drop City",                 type text},
        {"Drop State",                type text}
    }, MissingField.Ignore)
in
    Typed
