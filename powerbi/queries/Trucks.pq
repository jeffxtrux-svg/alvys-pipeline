// =============================================================================
// Trucks — lookup table: Id → truck number/name
//
// Paste as Blank Query, rename to "Trucks". Requires: SharedHelpers.
// =============================================================================
let
    RawTrucks = SharedHelpers[PaginateGet]("/trucks"),

    AsTable = Table.FromList(RawTrucks, Splitter.SplitByNothing(), {"Record"}),

    Expanded = Table.ExpandRecordColumn(AsTable, "Record",
        {"Id", "Number", "Name", "Status"}),

    // Display as Number if available, fall back to Name, then Id
    WithLabel = Table.AddColumn(Expanded, "Truck Label",
        each
            if [Number] <> null and [Number] <> "" then [Number]
            else if [Name] <> null and [Name] <> ""  then [Name]
            else [Id],
        type text),

    Selected = Table.SelectColumns(WithLabel, {"Id", "Truck Label"},
                    MissingField.Ignore),

    Typed = Table.TransformColumnTypes(Selected, {
        {"Id",          type text},
        {"Truck Label", type text}
    })
in
    Typed
