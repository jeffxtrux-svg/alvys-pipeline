// =============================================================================
// Users — lookup table: Id → full name
//
// Resolves CustomerSalesAgentId, CustomerLoadPlannerId, DispatcherId → names.
// Paste as Blank Query, rename to "Users". Requires: SharedHelpers.
// =============================================================================
let
    RawUsers = SharedHelpers[PaginateGet]("/users"),

    AsTable = Table.FromList(RawUsers, Splitter.SplitByNothing(), {"Record"}),

    Expanded = Table.ExpandRecordColumn(AsTable, "Record",
        {"Id", "FirstName", "LastName", "Email", "Status"}),

    WithName = Table.AddColumn(Expanded, "User Name",
        each
            let
                first = if [FirstName] = null then "" else [FirstName],
                last  = if [LastName]  = null then "" else [LastName],
                full  = Text.Trim(first & " " & last)
            in
                if full = "" then [Email] else full,
        type text),

    Selected = Table.SelectColumns(WithName, {"Id", "User Name"},
                    MissingField.Ignore),

    Typed = Table.TransformColumnTypes(Selected, {
        {"Id",        type text},
        {"User Name", type text}
    })
in
    Typed
