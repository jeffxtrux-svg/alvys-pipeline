// =============================================================================
// Fuel — Power Query M code, replaces the Excel-driven Fuel query.
//
// USAGE: Paste into Power Query Editor as Blank Query, rename to "Fuel".
// =============================================================================
let
    RawFuel = SharedHelpers[FetchFuel](),

    AsTable = Table.FromList(RawFuel, Splitter.SplitByNothing(), {"Record"}),

    Expanded = Table.ExpandRecordColumn(
        AsTable, "Record",
        {
            "TransactionId", "SubsidiaryName",
            "TruckNumber", "DriverName",
            "Source", "Type", "Category", "Description",
            "Location", "FuelTotal", "Fees", "Discounts", "Advances",
            "Total", "Quantity",
            "TransactionDate", "Invoice", "PaidStubbed",
            "RetailPPU", "DiscountPPU", "RetailCost"
        }
    ),

    // Helpers
    AmountOf = (rec) =>
        if rec = null or not (rec is record) then null
        else Record.FieldOrDefault(rec, "Amount", null),

    QuantityOf = (rec) =>
        if rec = null or not (rec is record) then null
        else Record.FieldOrDefault(rec, "Value", null),

    LocationField = (loc, fieldName as text) =>
        if loc = null or not (loc is record) then null
        else Record.FieldOrDefault(loc, fieldName, null),

    // Pull nested values out
    F1 = Table.AddColumn(Expanded, "Location ID",
            each LocationField([Location], "Id"), type text),
    F2 = Table.AddColumn(F1, "Location Name",
            each LocationField([Location], "Name"), type text),
    F3 = Table.AddColumn(F2, "City",
            each LocationField([Location], "City"), type text),
    F4 = Table.AddColumn(F3, "State",
            each LocationField([Location], "State"), type text),
    F5 = Table.AddColumn(F4, "Net Total",
            each AmountOf([FuelTotal]), type number),
    F6 = Table.AddColumn(F5, "Transaction Fee",
            each AmountOf([Fees]), type number),
    F7 = Table.AddColumn(F6, "Discount",
            each AmountOf([Discounts]), type number),
    F8 = Table.AddColumn(F7, "Total Due",
            each AmountOf([Total]), type number),
    F9 = Table.AddColumn(F8, "Quantity",
            each QuantityOf([Quantity]), type number),

    Renamed = Table.RenameColumns(F9, {
        {"TransactionId", "Transaction Id"},
        {"SubsidiaryName", "Subsidiary"},
        {"TruckNumber", "Truck"},
        {"DriverName", "Driver"},
        {"Category", "Fuel Transaction Type"},
        {"Description", "Fuel Provider Description"},
        {"TransactionDate", "Transaction Date"},
        {"PaidStubbed", "Paid / Stubbed"},
        {"RetailPPU", "Retail PPU"},
        {"DiscountPPU", "Discount PPU"},
        {"RetailCost", "Retail Cost"}
    }, MissingField.Ignore),

    Cleaned = Table.RemoveColumns(Renamed,
        {"Location", "FuelTotal", "Fees", "Discounts", "Advances",
         "Total", "Source", "Type"},
        MissingField.Ignore),

    Typed = Table.TransformColumnTypes(Cleaned, {
        {"Transaction Id",          type text},
        {"Subsidiary",              type text},
        {"Truck",                   type text},
        {"Driver",                  type text},
        {"Fuel Transaction Type",   type text},
        {"Fuel Provider Description", type text},
        {"Transaction Date",        type datetime},
        {"Paid / Stubbed",          type text},
        {"Location ID",             type text},
        {"Location Name",           type text},
        {"City",                    type text},
        {"State",                   type text},
        {"Net Total",               type number},
        {"Transaction Fee",         type number},
        {"Discount",                type number},
        {"Total Due",               type number},
        {"Quantity",                type number},
        {"Retail PPU",              type number},
        {"Discount PPU",            type number},
        {"Retail Cost",             type number},
        {"Invoice",                 type text}
    }, MissingField.Ignore)
in
    Typed
