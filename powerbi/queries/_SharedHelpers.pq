// =============================================================================
// SharedHelpers — Alvys API authentication + paginated search
//
// USAGE: Paste this into Power Query Editor as a new Blank Query, then
// rename the query to "SharedHelpers" in the left panel. Other queries
// reference it via: SharedHelpers[PaginateSearch]("/loads/search", body)
//
// REQUIRES three Power BI parameters:
//   - AlvysClientId      (Text)
//   - AlvysClientSecret  (Text)
//   - AlvysStartDate     (Text, e.g. "2024-01-01")
// =============================================================================
let
    // -- Constants (mirror src/alvys_client.py) -------------------------------
    AuthBaseUrl  = "https://auth.alvys.com",
    ApiBaseUrl   = "https://integrations.alvys.com",
    Audience     = "https://api.alvys.com/public/",
    ApiVersion   = "1",
    PageSize     = 100,

    // -- OAuth2 client_credentials (Auth0-style: JSON body, audience required)
    GetToken = () =>
        let
            BodyJson = Json.FromValue([
                client_id     = AlvysClientId,
                client_secret = AlvysClientSecret,
                audience      = Audience,
                grant_type    = "client_credentials"
            ]),
            Resp = Json.Document(
                Web.Contents(
                    AuthBaseUrl,
                    [
                        RelativePath = "/oauth/token",
                        Headers      = [#"Content-Type" = "application/json"],
                        Content      = BodyJson
                    ]
                )
            )
        in
            Resp[access_token],

    // Token is cached for the duration of this refresh. M's lazy evaluation
    // means GetToken() runs exactly once even though many queries reference it.
    Token = GetToken(),

    AuthHeaders = [
        Authorization    = "Bearer " & Token,
        #"Content-Type"  = "application/json",
        Accept           = "application/json"
    ],

    // -- Extract the records list from a paginated response. The Alvys API
    // returns either a bare array or an object with one of these keys.
    ExtractItems = (resp as any) as list =>
        if Value.Is(resp, type list) then resp
        else if resp is record then
            let
                items = Record.FieldOrDefault(resp, "Items",
                        Record.FieldOrDefault(resp, "items",
                        Record.FieldOrDefault(resp, "data",
                        Record.FieldOrDefault(resp, "results", {}))))
            in items
        else {},

    // -- Fetch a single page of /<resource>/search
    FetchPage = (path as text, baseBody as record, pageNum as number) =>
        let
            FullBody = Record.AddField(
                Record.AddField(baseBody, "page", pageNum),
                "pageSize", PageSize
            ),
            Resp = Json.Document(
                Web.Contents(
                    ApiBaseUrl,
                    [
                        RelativePath = "/api/p/v" & ApiVersion & path,
                        Headers      = AuthHeaders,
                        Content      = Json.FromValue(FullBody)
                    ]
                )
            )
        in
            ExtractItems(Resp),

    // -- Paginate until we get a short page (< PageSize) or an empty page
    PaginateSearch = (path as text, baseBody as record) as list =>
        let
            Pages = List.Generate(
                () => [page = 0, items = FetchPage(path, baseBody, 0)],
                each List.Count([items]) > 0,
                each
                    let
                        // Stop if last page was short — no more results.
                        nextItems =
                            if List.Count([items]) < PageSize then {}
                            else FetchPage(path, baseBody, [page] + 1)
                    in
                        [page = [page] + 1, items = nextItems],
                each [items]
            )
        in
            List.Combine(Pages),

    // -- GET paginator (for /drivers, /trucks, /trailers etc.)
    FetchGetPage = (path as text, pageNum as number) =>
        let
            Resp = Json.Document(
                Web.Contents(
                    ApiBaseUrl,
                    [
                        RelativePath = "/api/p/v" & ApiVersion & path,
                        Headers      = AuthHeaders,
                        Query        = [page = Number.ToText(pageNum),
                                        pageSize = Number.ToText(PageSize)]
                    ]
                )
            )
        in
            ExtractItems(Resp),

    PaginateGet = (path as text) as list =>
        let
            Pages = List.Generate(
                () => [page = 0, items = FetchGetPage(path, 0)],
                each List.Count([items]) > 0,
                each
                    let
                        nextItems =
                            if List.Count([items]) < PageSize then {}
                            else FetchGetPage(path, [page] + 1)
                    in
                        [page = [page] + 1, items = nextItems],
                each [items]
            )
        in
            List.Combine(Pages),

    // -- Standard date range used by search endpoints
    DateRange =
        let
            StartIso = AlvysStartDate & "T00:00:00Z",
            // End = now UTC, but Power Query doesn't have a clean UTC-now;
            // DateTime.LocalNow() works fine since Alvys treats end-of-range
            // as inclusive
            EndIso   = DateTime.ToText(DateTime.LocalNow(),
                                       "yyyy-MM-ddTHH:mm:ssZ")
        in
            [start = StartIso, #"end" = EndIso],

    // -- Resource-specific helpers ---------------------------------------------
    FetchLoads = () =>
        PaginateSearch("/loads/search", [
            status = {
                "Open", "Queued", "Covered", "Dispatched", "In Transit",
                "Released", "Invoiced", "Completed", "Cancelled"
            },
            updatedAtRange = DateRange
        ]),

    FetchTrips = () =>
        PaginateSearch("/trips/search", [
            status = {
                "Open", "Covered", "Dispatched", "In Transit", "Delivered",
                "Released", "Invoiced", "Completed", "Cancelled"
            },
            updatedAtRange = DateRange
        ]),

    FetchFuel = () =>
        PaginateSearch("/fuel/search", [
            transactionRange = DateRange
        ]),

    // -- Public surface --------------------------------------------------------
    Public = [
        Token          = Token,
        PaginateSearch = PaginateSearch,
        PaginateGet    = PaginateGet,
        FetchLoads     = FetchLoads,
        FetchTrips     = FetchTrips,
        FetchFuel      = FetchFuel
    ]
in
    Public
