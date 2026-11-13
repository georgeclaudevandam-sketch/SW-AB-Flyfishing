# Eastern Slopes Trout Map

An interactive fly-fishing map of Alberta's Eastern Slopes, from Grande Cache south to the US border.
Pick one, several or all trout species and see where to find them.

**Live map:** https://georgeclaudevandam-sketch.github.io/SW-AB-Flyfishing/

## Data
Every lake, pond, reservoir, river, creek and stream in the Eastern Slopes comes from the Government of Alberta
**Fisheries and Wildlife Management Information System (FWMIS)** public map service
([layers 33 and 34](https://geospatial.alberta.ca/titan/rest/services/biota/fwimt_pub_species_inventory/MapServer)),
with the species codes FWMIS has recorded in each waterbody. Lake stocking records come from layer 32.
Nothing in `data/water/` is entered by hand. `scripts/build_fwmis.py` downloads the data and writes
`data/water/index.json` plus geometry chunks.

## Features
- Species filter using Alberta's four-letter codes (BLTR, WSCT, GOTR, ARGR, CRTR, ...), "any" or "all selected", All / None
- Lakes and streams drawn and coloured by the rarest species recorded; code labels beside each water when zoomed in
- Stream-size filter (Strahler order), stocked-lake filter, option to show waters with no fish records
- Basemaps: OpenTopoMap, NRCan Toporama, CyclOSM (tracks and cutlines), OpenStreetMap, Esri topo and satellite; trail, road and hillshade overlays
- Route planner with snap-to-trail (online), distance, GPX export and saved routes
- Installable, offline-capable app; download all water data and map tiles for an area; GPX / KML / GeoJSON export
- Desktop layout with filters, searchable list and detail panel; compact layout on phones

## Important
A species is listed if FWMIS has ever recorded it anywhere in that waterbody; that is not a guarantee it is there now or at a given spot.
FWMIS does not cover Banff, Jasper or Waterton national parks. Always check the current [Alberta Guide to Sportfishing Regulations](https://albertaregulations.ca/fishingregs/),
[My Wild Alberta](https://mywildalberta.ca/fishing/) and, in Banff, Jasper and Waterton,
[Parks Canada fishing rules](https://parks.canada.ca/voyage-travel/experience/peche-fishing).
Bull trout, westslope cutthroat and Athabasca rainbow are catch-and-release in most waters.

Fish data: Government of Alberta (FWMIS). Map data © OpenStreetMap contributors, OpenTopoMap, CyclOSM, Waymarked Trails, Natural Resources Canada and Esri.
