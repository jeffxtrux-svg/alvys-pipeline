// =============================================================================
// Drivers — lookup table: Id → full name
//
// Used by Loads and Trips queries to resolve Driver1.Id → "First Last".
// Paste as Blank Query, rename to "Drivers". Requires: SharedHelpers.
// =============================================================================
let
    RawDrivers = SharedHelpers[PaginateGet]("/drivers"),

    AsTable = Table.FromList(RawDrivers, Splitter.SplitByNothing(), {"Record"}),

    Expanded = Table.ExpandRecordColumn(AsTable, "Record",
        {"Id", "FirstName", "LastName", "Status"}),

    WithName = Table.AddColumn(Expanded, "Driver Name",
        each
            let
                first = if [FirstName] = null then "" else [FirstName],
                last  = if [LastName]  = null then "" else [LastName],
                full  = Text.Trim(first & " " & last)
            in
                if full = "" then null else full,
        type text),

    Selected = Table.SelectColumns(WithName, {"Id", "Driver Name"},
                    MissingField.Ignore),

    Typed = Table.TransformColumnTypes(Selected, {
        {"Id",          type text},
        {"Driver Name", type text}
    })
in
    Typed
