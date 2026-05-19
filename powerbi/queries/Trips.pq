// =============================================================================
// Trips — Power Query M code, replaces the Excel-driven Trips query.
//
// Includes the Driver Rate calculation (RatesV2 with legacy fallback) plus
// the columns the visuals reference.
//
// USAGE: Paste into Power Query Editor as Blank Query, rename to "Trips".
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
            "TripValue", "Driver1", "Driver2", "Truck", "Trailer",
            "Carrier", "Stops", "DispatcherId",
            "UpdatedAt"
        }
    ),

    // ----------------------------------------------------------------------
    // Helpers (lifted into the main let scope so they can be reused)
    // ----------------------------------------------------------------------
    DistanceOf = (rec) =>
        if rec = null or not (rec is record) then null
        else
            let
                d = Record.FieldOrDefault(rec, "Distance", null)
            in
                if d is record then Record.FieldOrDefault(d, "Value", null)
                else null,

    AmountOf = (rec) =>
        if rec = null or not (rec is record) then null
        else Record.FieldOrDefault(rec, "Amount", null),

    // Case-insensitive multi-key field access on a record
    Field = (r, keys as list) =>
        if r = null or not (r is record) then null
        else
            List.First(
                List.RemoveNulls(
                    List.Transform(keys, each Record.FieldOrDefault(r, _, null))
                ),
                null
            ),

    // Read a flat rate from a tier object. For single-tier (most common)
    // this is just tiers[0].rate. For multi-tier we'd need to sum brackets,
    // but the data shows almost everyone is single-tier, so we take the
    // FIRST tier's rate as the effective rate.
    // TODO: implement true multi-tier bracket calculation
    SingleTierRate = (tierObj) =>
        if tierObj = null or not (tierObj is record) then 0
        else
            let
                tiers = Field(tierObj, {"tiers", "Tiers"}),
                fromTier =
                    if tiers is list and not List.IsEmpty(tiers)
                        and tiers{0} is record
                    then Field(tiers{0}, {"rate", "Rate"})
                    else null,
                flat = if fromTier <> null then fromTier
                       else Field(tierObj, {"rate", "Rate"})
            in
                if flat is number then flat else 0,

    // Look up a rate in legacy Driver1.Rates[] by RateType
    LegacyRateForType = (ratesList, rateType as text) =>
        if not (ratesList is list) then 0
        else
            let
                match = List.First(
                    List.Select(ratesList, each
                        _ is record and
                        Record.FieldOrDefault(_, "RateType", "") = rateType),
                    null),
                rate = if match <> null then Record.FieldOrDefault(match, "Rate", 0)
                       else 0
            in
                if rate is number then rate else 0,

    // Calculate driver mileage pay for one trip
    CalcDriverRate = (trip as record) =>
        let
            driver1 = Record.FieldOrDefault(trip, "Driver1", null),
            loadedMiles = let v = DistanceOf(Record.FieldOrDefault(trip, "LoadedMileage", null))
                          in if v is number then v else 0,
            emptyMiles  = let v = DistanceOf(Record.FieldOrDefault(trip, "EmptyMileage", null))
                          in if v is number then v else 0,

            // Try RatesV2 first (modern, list of policies)
            ratesV2 = if driver1 is record then Field(driver1, {"RatesV2", "ratesV2"}) else null,
            v2Pay =
                if ratesV2 is list and not List.IsEmpty(ratesV2) then
                    let
                        LoadedRateSum = List.Sum(List.Transform(ratesV2, each
                            SingleTierRate(Field(_, {"loadedMilesRate", "LoadedMilesRate"})))),
                        EmptyRateSum = List.Sum(List.Transform(ratesV2, each
                            SingleTierRate(Field(_, {"emptyMilesRate", "EmptyMilesRate"}))))
                    in
                        (LoadedRateSum * loadedMiles) + (EmptyRateSum * emptyMiles)
                else 0,

            // Fall back to legacy Rates if V2 didn't yield anything
            legacyPay =
                if v2Pay > 0 then 0
                else
                    let
                        rates = if driver1 is record then
                            Record.FieldOrDefault(driver1, "Rates", {})
                            else {},
                        LoadedRate = LegacyRateForType(rates, "Loaded Miles"),
                        EmptyRate  = LegacyRateForType(rates, "Empty Miles")
                    in
                        (LoadedRate * loadedMiles) + (EmptyRate * emptyMiles)
        in
            v2Pay + legacyPay,

    // ----------------------------------------------------------------------
    // Build the table columns by row
    // ----------------------------------------------------------------------
    WithDriverRate = Table.AddColumn(Expanded, "Driver Rate",
        each CalcDriverRate(_), type number),

    WithLoadedMi = Table.AddColumn(WithDriverRate, "Loaded Mileage",
        each DistanceOf([LoadedMileage]), type number),

    WithEmptyMi  = Table.AddColumn(WithLoadedMi, "Empty Mileage",
        each DistanceOf([EmptyMileage]), type number),

    WithTotalMi  = Table.AddColumn(WithEmptyMi, "Total Mileage",
        each DistanceOf([TotalMileage]), type number),

    WithTripValue = Table.AddColumn(WithTotalMi, "Trip Value",
        each AmountOf([TripValue]), type number),

    // Per Alvys: carrier rate (for brokered trips) lives at Carrier.Rate.Amount
    WithCarrierRate = Table.AddColumn(WithTripValue, "Carrier Rate",
        each
            if [Carrier] = null or not ([Carrier] is record) then null
            else AmountOf(Record.FieldOrDefault([Carrier], "Rate", null)),
        type number),

    WithCarrierName = Table.AddColumn(WithCarrierRate, "Carrier Name",
        each
            if [Carrier] = null or not ([Carrier] is record) then null
            else Record.FieldOrDefault([Carrier], "Name",
                 Record.FieldOrDefault([Carrier], "ExternalName", null)),
        type text),

    // Driver / Truck / Trailer extraction (IDs only — name resolution would
    // require a separate Drivers/Trucks/Trailers lookup query, future phase)
    WithDriver1 = Table.AddColumn(WithCarrierName, "Driver 1 Id",
        each if [Driver1] is record then Record.FieldOrDefault([Driver1], "Id", null)
             else null, type text),

    WithDriver1Fleet = Table.AddColumn(WithDriver1, "Driver 1 Fleet",
        each if [Driver1] is record then
                let f = Record.FieldOrDefault([Driver1], "Fleet", null)
                in if f is record then Record.FieldOrDefault(f, "Name", null) else null
             else null, type text),

    WithTruckNum = Table.AddColumn(WithDriver1Fleet, "Truck Number",
        each if [Truck] is record then
                Record.FieldOrDefault([Truck], "Number",
                Record.FieldOrDefault([Truck], "Id", null))
             else null, type text),

    WithTrailerNum = Table.AddColumn(WithTruckNum, "Trailer Number",
        each if [Trailer] is record then
                Record.FieldOrDefault([Trailer], "Number",
                Record.FieldOrDefault([Trailer], "Id", null))
             else null, type text),

    // ----------------------------------------------------------------------
    // Final shape: drop raw nested fields, rename, type
    // ----------------------------------------------------------------------
    Renamed = Table.RenameColumns(WithTrailerNum, {
        {"TripNumber", "Trip #"},
        {"LoadNumber", "Load #"},
        {"OrderNumber", "Order #"},
        {"Status", "Trip Status"},
        {"TenderAs", "Tender As"},
        {"PickupDate", "Scheduled Pickup"},
        {"DeliveryDate", "Scheduled Delivery"},
        {"PickedUpAt", "Dispatched Date Raw"},
        {"CarrierAssignedAt", "Dispatched Date"}
    }, MissingField.Ignore),

    Cleaned = Table.RemoveColumns(Renamed,
        {"LoadedMileage", "EmptyMileage", "TotalMileage", "TripValue",
         "Driver1", "Driver2", "Truck", "Trailer", "Carrier", "Stops",
         "DeliveredAt", "ReleasedAt", "DispatcherId", "UpdatedAt",
         "TenderAsSubsidiaryType"},
        MissingField.Ignore),

    Typed = Table.TransformColumnTypes(Cleaned, {
        {"Trip #",             type text},
        {"Load #",             type text},
        {"Order #",            type text},
        {"Trip Status",        type text},
        {"Tender As",          type text},
        {"Scheduled Pickup",   type datetime},
        {"Scheduled Delivery", type datetime},
        {"Dispatched Date",    type datetime},
        {"Driver Rate",        type number},
        {"Trip Value",         type number},
        {"Loaded Mileage",     type number},
        {"Empty Mileage",      type number},
        {"Total Mileage",      type number},
        {"Carrier Rate",       type number},
        {"Carrier Name",       type text},
        {"Driver 1 Id",        type text},
        {"Driver 1 Fleet",     type text},
        {"Truck Number",       type text},
        {"Trailer Number",     type text}
    }, MissingField.Ignore)
in
    Typed
