"""Shared types: Pydantic models for API responses, TypedDicts for
internal dict shapes, dataclasses for config.

Design split:
- **Pydantic** — external data at the boundary (API responses). Catches
  schema drift at runtime.
- **TypedDict** — dict shapes we produce internally. Typed access, no runtime cost.
- **@dataclass** — config and intermediate structures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, RootModel

# --- Pydantic models: external API responses ---


class _ExtraIgnore(BaseModel):
    """Base with tolerant parsing — APIs evolve, we ignore unknown keys."""

    model_config = ConfigDict(extra="ignore")


class PlacesLocation(_ExtraIgnore):
    latitude: float
    longitude: float


class PlacesAddressComponent(_ExtraIgnore):
    shortText: str = ""
    types: list[str] = []


class PlacesDisplayName(_ExtraIgnore):
    text: str = ""
    languageCode: str = ""


class PlacesHours(_ExtraIgnore):
    weekdayDescriptions: list[str] = []


class PlacesPlace(_ExtraIgnore):
    """One entry from places:searchText or places:searchNearby."""

    id: str = ""
    formattedAddress: str = ""
    location: PlacesLocation | None = None
    addressComponents: list[PlacesAddressComponent] = []
    displayName: PlacesDisplayName | None = None
    types: list[str] = []
    primaryType: str = ""
    googleMapsUri: str = ""
    websiteUri: str = ""
    businessStatus: str = ""
    rating: float | None = None
    userRatingCount: int | None = None
    priceLevel: str = ""
    regularOpeningHours: PlacesHours | None = None


class PlacesResponse(_ExtraIgnore):
    places: list[PlacesPlace] = []


class RoutesRoute(_ExtraIgnore):
    duration: str = ""
    distanceMeters: int = 0


class RoutesResponse(_ExtraIgnore):
    routes: list[RoutesRoute] = []


class OverpassElement(_ExtraIgnore):
    tags: dict[str, str] = {}


class OverpassResponse(_ExtraIgnore):
    elements: list[OverpassElement] = []


class NominatimResult(_ExtraIgnore):
    lat: str
    lon: str
    display_name: str = ""


class NominatimResponse(RootModel[list[NominatimResult]]):
    """Nominatim returns a JSON array, not an envelope object."""


# --- Sheets API: OAuth token + service-account key ---


class AccessTokenResponse(_ExtraIgnore):
    """Response from the OAuth2 token endpoint. Covers all three grants we use:
    JWT-bearer and refresh return ``access_token``; the authorization-code grant
    (one-time consent) additionally returns a ``refresh_token``. Fields are
    snake_case in Google's response, so N815 doesn't apply."""

    access_token: str = ""
    expires_in: int = 3600
    token_type: str = ""
    refresh_token: str = ""
    scope: str = ""


class ServiceAccountKey(_ExtraIgnore):
    """The subset of a service-account JSON key file we need to mint a JWT.
    The key's token_uri is ignored — it is the same OAuth endpoint for every
    Google service account (see ``_google.OAUTH_ENDPOINT``)."""

    client_email: str
    private_key: str


# --- OAuth-user auth: installed-app client + stored token ---


class OAuthInstalledClient(_ExtraIgnore):
    """The client block of a Google Desktop OAuth client-secrets file (the
    ``installed`` or ``web`` object). Snake_case fields are Google's own."""

    client_id: str
    client_secret: str
    auth_uri: str = "https://accounts.google.com/o/oauth2/auth"
    # The default token endpoint, not a secret — S105 is a false positive here.
    token_uri: str = "https://oauth2.googleapis.com/token"  # noqa: S105
    redirect_uris: list[str] = []


class OAuthClientConfig(_ExtraIgnore):
    """A Google OAuth client-secrets file: an ``installed`` (Desktop) or ``web``
    block. We use the Desktop/installed-app loopback flow."""

    installed: OAuthInstalledClient | None = None
    web: OAuthInstalledClient | None = None


class OAuthToken(_ExtraIgnore):
    """Our stored OAuth token file, written by ``docs auth-login`` and read on
    every unattended run. Only the refresh token is load-bearing; the access
    token and scopes are kept for debugging."""

    refresh_token: str = ""
    access_token: str = ""
    scopes: list[str] = []


# --- Sheets API: spreadsheets.values responses ---
#
# A cell is str | int | float | bool: FORMATTED_VALUE reads return every cell as
# a string, but UNFORMATTED_VALUE and FORMULA reads return raw numbers/booleans,
# so the value grid is union-typed. Callers that need string semantics (the
# header/key logic) stringify first. Rows may be short (the API drops trailing
# empty cells) — callers pad.

SheetCell = str | int | float | bool | None


class ValueRange(_ExtraIgnore):
    """A range of values (spreadsheets.values.get / the unit of batch I/O)."""

    range: str = ""
    majorDimension: str = "ROWS"
    values: list[list[SheetCell]] = []


class UpdateValuesResponse(_ExtraIgnore):
    spreadsheetId: str = ""
    updatedRange: str = ""
    updatedRows: int = 0
    updatedColumns: int = 0
    updatedCells: int = 0


class AppendUpdate(_ExtraIgnore):
    """The ``updates`` block of an append response."""

    updatedRange: str = ""
    updatedRows: int = 0
    updatedCells: int = 0


class AppendValuesResponse(_ExtraIgnore):
    spreadsheetId: str = ""
    tableRange: str = ""
    updates: AppendUpdate | None = None


class BatchUpdateValuesResponse(_ExtraIgnore):
    spreadsheetId: str = ""
    totalUpdatedRows: int = 0
    totalUpdatedCells: int = 0
    responses: list[UpdateValuesResponse] = []


class BatchGetValuesResponse(_ExtraIgnore):
    """Several ranges read in one call (spreadsheets.values.batchGet)."""

    spreadsheetId: str = ""
    valueRanges: list[ValueRange] = []


class ClearValuesResponse(_ExtraIgnore):
    spreadsheetId: str = ""
    clearedRange: str = ""


class BatchClearValuesResponse(_ExtraIgnore):
    spreadsheetId: str = ""
    clearedRanges: list[str] = []


# --- Sheets API: spreadsheet & sheet metadata / structural responses ---


class GridProperties(_ExtraIgnore):
    rowCount: int = 0
    columnCount: int = 0


class SheetProperties(_ExtraIgnore):
    """One sheet's properties (a tab within the spreadsheet)."""

    sheetId: int = 0
    title: str = ""
    index: int = 0
    sheetType: str = ""
    gridProperties: GridProperties | None = None
    hidden: bool = False


class SheetEntry(_ExtraIgnore):
    properties: SheetProperties | None = None


class SpreadsheetMeta(_ExtraIgnore):
    """Spreadsheet metadata; read to list existing sheets (titles + sheetIds)."""

    sheets: list[SheetEntry] = []


class DuplicateSheetReply(_ExtraIgnore):
    """The ``duplicateSheet`` reply: the new sheet's properties."""

    properties: SheetProperties | None = None


class FindReplaceReply(_ExtraIgnore):
    """The ``findReplace`` reply: counts of what changed."""

    occurrencesChanged: int = 0
    valuesChanged: int = 0
    rowsChanged: int = 0
    sheetsChanged: int = 0
    formulasChanged: int = 0


class BatchUpdateReply(_ExtraIgnore):
    """One reply in a batchUpdate response. Only the request types we read back
    (duplicateSheet, findReplace) are modeled; the rest are ignored."""

    duplicateSheet: DuplicateSheetReply | None = None
    findReplace: FindReplaceReply | None = None


class BatchUpdateSpreadsheetResponse(_ExtraIgnore):
    spreadsheetId: str = ""
    replies: list[BatchUpdateReply] = []


class SpreadsheetProperties(_ExtraIgnore):
    title: str = ""


class CreateSpreadsheetResponse(_ExtraIgnore):
    """Response from spreadsheets.create — the new spreadsheet's id and URL."""

    spreadsheetId: str = ""
    spreadsheetUrl: str = ""
    properties: SpreadsheetProperties | None = None


# --- Sheets API: structured error body (Google standard, AIP-193) ---


class GoogleApiError(_ExtraIgnore):
    """The ``error`` object Google returns on a failed call: an HTTP ``code``, a
    machine ``status`` (e.g. PERMISSION_DENIED, RESOURCE_EXHAUSTED), and a human
    ``message``."""

    code: int = 0
    status: str = ""
    message: str = ""


class GoogleApiErrorEnvelope(_ExtraIgnore):
    """The top-level ``{"error": {...}}`` wrapper of a Google error response."""

    error: GoogleApiError | None = None


# --- Sheets CLI input (parsed from --values / --set / --ops JSON) ---
#
# A boundary too: untrusted CLI JSON. Parse via these models so json.loads'
# Any never enters the type graph. Cells stay union-typed (the caller
# stringifies); numbers/booleans are accepted so '{"Spent": 1240}' works.
# ``SheetCell`` is defined above (shared with the values-response models).


class CellGrid(RootModel[list[list[SheetCell]]]):
    """A 2-D array of cells parsed from ``--values``."""


class CellObject(RootModel[dict[str, SheetCell]]):
    """A column-name -> value object parsed from ``--set``."""


class BatchOp(_ExtraIgnore):
    """One ``--ops`` entry: a range and the 2-D values to write there."""

    range: str
    values: list[list[SheetCell]] = []


class BatchOps(RootModel[list[BatchOp]]):
    """The ``--ops`` payload: a list of {range, values}."""


class RangeList(RootModel[list[str]]):
    """The ``--ranges`` payload: a JSON array of A1 ranges (batch-get/clear)."""


# --- Docs API: document structure (read) ---
#
# A Google Doc is a tree of structural elements addressed by UTF-16 index, not a
# grid. We model only the slice the CLI reads back: text runs and their indexes
# (for the get index-map and append end-index), plus named ranges. The raw
# escape hatch (get --raw-json) uses DocsRawDocument to keep every field.


class DocsTextRun(_ExtraIgnore):
    """A run of text with one consistent style."""

    content: str = ""


class DocsParagraphElement(_ExtraIgnore):
    startIndex: int = 0
    endIndex: int = 0
    textRun: DocsTextRun | None = None


class DocsParagraph(_ExtraIgnore):
    elements: list[DocsParagraphElement] = []


class DocsStructuralElement(_ExtraIgnore):
    """One element of a body/segment: a paragraph, table, etc. We read indexes
    and (for paragraphs) the text runs; other element types are ignored."""

    startIndex: int = 0
    endIndex: int = 0
    paragraph: DocsParagraph | None = None


class DocsBody(_ExtraIgnore):
    content: list[DocsStructuralElement] = []


class DocsNamedRange(_ExtraIgnore):
    namedRangeId: str = ""
    name: str = ""


class DocsNamedRangeGroup(_ExtraIgnore):
    """All named ranges that share a name (``namedRanges`` is keyed by name)."""

    name: str = ""
    namedRanges: list[DocsNamedRange] = []


class DocumentModel(_ExtraIgnore):
    """The typed slice of a ``documents.get`` response: identity, the revision
    (for write-control), the body (for index math), and named ranges."""

    documentId: str = ""
    title: str = ""
    revisionId: str = ""
    body: DocsBody | None = None
    namedRanges: dict[str, DocsNamedRangeGroup] = {}


class DocsRawDocument(RootModel[dict[str, object]]):
    """The full ``documents.get`` response, untyped, for the raw-json escape hatch."""


# --- Docs API: batchUpdate reply ---


class DocsReplaceAllTextReply(_ExtraIgnore):
    occurrencesChanged: int = 0


class DocsCreateNamedRangeReply(_ExtraIgnore):
    namedRangeId: str = ""


class DocsBatchUpdateReply(_ExtraIgnore):
    """One reply in a Docs batchUpdate response. Only the replies we surface
    (replaceAllText counts, createNamedRange ids) are modeled; the rest ignored."""

    replaceAllText: DocsReplaceAllTextReply | None = None
    createNamedRange: DocsCreateNamedRangeReply | None = None


class DocsBatchUpdateResponse(_ExtraIgnore):
    documentId: str = ""
    replies: list[DocsBatchUpdateReply] = []


# --- Drive API: file metadata / list (Docs cannot list/export/copy alone) ---


class DriveFile(_ExtraIgnore):
    id: str = ""
    name: str = ""
    mimeType: str = ""


class DriveFileList(_ExtraIgnore):
    files: list[DriveFile] = []
    nextPageToken: str = ""


# --- Docs CLI input (parsed from --requests JSON) ---


class BatchRequests(RootModel[list[dict[str, object]]]):
    """The ``--requests`` payload: raw Docs batchUpdate request objects, passed
    through untouched so every request type is reachable without modeling each."""


# --- TypedDicts: internal dict shapes ---

GapReason = Literal["missing", "empty", "non_latin", "refresh", "malformed"]
Confidence = Literal["high", "medium", "low"]
Source = Literal["google-places", "nominatim"]
ValueInputOption = Literal["USER_ENTERED", "RAW"]


class TableRow(TypedDict):
    """A read-table data row: its 1-based sheet row plus the named cells. The
    row number lets callers write specific cells back (e.g. fill one MSRP)."""

    row: int
    cells: dict[str, str]


class StationInfo(TypedDict):
    """All four fields always present; values may be None when a given
    lookup failed (OSM had no line tags, Routes API errored, etc.).

    ``station_lines_fetched`` distinguishes "Overpass confirmed empty"
    (True + None) from "we never asked Overpass or it was unreachable"
    (False + None). Refresh mode preserves existing values on False so
    transient Overpass 504s don't clear hand-entered data.
    """

    nearest_station: str
    walk_time_to_station: int | None
    station_lines: str | None
    station_lines_fetched: bool


class Enrichment(TypedDict):
    """All fields always populated (empty strings when absent)."""

    website: str
    hours: str
    closed: str


class _GeoResultBase(TypedDict):
    coordinates: str
    address: str
    address_local: str
    google_maps_url: str
    place_id: str
    confidence: Confidence
    candidates: int
    source: Source


class GeoResult(_GeoResultBase, total=False):
    """Base fields always present; ``enrichment`` only when ``--enrich``,
    ``station`` only when ``--stations``. ``url_validation_failed`` is set
    when the URL pipeline refused to emit a ``google_maps_url`` — closed
    venue per ``businessStatus``, or a Google match that returned no
    ``googleMapsUri`` — so callers can surface the issue to the user instead
    of silently dropping the field. (A Nominatim fallback geocodes fine
    without a Google URL and is not flagged.)
    """

    enrichment: Enrichment
    station: StationInfo
    url_validation_failed: str


# --- Config dataclasses ---


@dataclass(frozen=True, slots=True)
class GeocodeOptions:
    """Knobs for a geocoding call. Defaults match the cheapest SKU path.

    Station filling splits into two dimensions, each controlled independently
    so the slow Overpass path can be opted into separately from the fast
    Google path:

    - ``stations`` — Google only: ``nearest_station`` + ``walk_time_to_station``.
      Fast and stable.
    - ``lines`` — Overpass/OSM only: ``station_lines``. Slow (1.1s throttle,
      frequent 504s) and optional. Requires either ``stations=True`` or a
      pre-existing ``nearest_station`` anchor.
    """

    enrich: bool = False
    need_local: bool = True
    stations: bool = False
    lines: bool = False
    # If set, anchor station lookups to this existing name (geocode it and
    # compute walk/lines from its coords) instead of running Places Nearby.
    # Prevents mismatched data when the file already has a nearest_station.
    existing_station_name: str | None = None


@dataclass(slots=True)
class Station:
    """Candidate station from Places Nearby."""

    name: str
    lat: float
    lng: float
    types: list[str] = field(default_factory=list)


VenueOutcomeKind = Literal["no_gaps", "not_found", "no_new_data", "updated"]


@dataclass(slots=True)
class VenueOutcome:
    """Result of running the per-venue geocode pipeline on one file."""

    path: Path
    gaps: dict[str, GapReason]
    kind: VenueOutcomeKind
    query: str = ""
    result: GeoResult | None = None
    updates: dict[str, object] = field(default_factory=dict)
    # Distinguishes "updates computed, file written" from "updates computed,
    # write=False (dry-run)". Callers need both states to render correctly.
    written: bool = False
