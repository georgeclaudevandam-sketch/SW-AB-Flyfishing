# Eastern Slopes Trout Map

An interactive fly-fishing map of Alberta's Eastern Slopes, from Grande Cache south to the US border.
Pick one, several or all trout species and see where to find them.

**Live map:** https://georgeclaudevandam-sketch.github.io/SW-AB-Flyfishing/

## Features
- Species filter (12 species, with four-letter codes), "any" or "all selected" matching, All / None buttons
- Trip type (roadside, day hike, multi-day), max round-trip distance, month (hides closed or frozen water), drainage, Alberta vs national-park waters
- Species-code labels beside each lake and stream, plus a legend
- Basemaps: OpenTopoMap, NRCan Toporama (Canada topo), CyclOSM (tracks, cutlines, OHV trails), OpenStreetMap roads, Esri World Topo and satellite; overlays for hiking trails, roads and hillshade
- Route planner: tap to draw, drag to adjust, optional snap to trails (online), out-and-back distance and time, GPX export, save routes on the device
- Works offline as an installable app ("Add to Home Screen"); save map tiles for an area; export sites to GPX / KML / GeoJSON for Gaia, onX, CalTopo or Avenza
- Desktop layout with filters, sortable site table and detail panel; compact layout on phones

## Editing the data
All sites are in [`data/sites.json`](data/sites.json); species are in [`data/species.json`](data/species.json).
Each site has:

| field | meaning |
|---|---|
| `id`, `name`, `type`, `region` | identity; `type` is lake, river or creek |
| `lat`, `lng` | approximate location (decimal degrees) |
| `species` | list of codes, e.g. `["WSCT","BLTR"]` |
| `access`, `rtKm` | `roadside`, `day` or `multiday`; approximate round-trip km |
| `trailhead` | where to start |
| `season`, `openMonths`, `iceFreeMonths` | season text and month numbers (1 to 12) used by the month filter |
| `flies`, `notes`, `regs` | free text; leave `flies` empty if unknown |
| `permit` | `Alberta` or `Parks Canada` |
| `verify` | `true` if the entry still needs checking |

## Important
Locations, seasons, species and distances are **approximate and for planning only**. Many entries are flagged `verify`.
Always check the current [Alberta Guide to Sportfishing Regulations](https://albertaregulations.ca/fishingregs/),
[My Wild Alberta](https://mywildalberta.ca/fishing/) and, in Banff, Jasper and Waterton,
[Parks Canada fishing rules](https://parks.canada.ca/voyage-travel/experience/peche-fishing).
Bull trout, westslope cutthroat and Athabasca rainbow are catch-and-release in most waters.

Golden trout lakes are from Alberta Conservation Association's survey of high mountain lakes in southwest Alberta.
Map data © OpenStreetMap contributors, OpenTopoMap, CyclOSM, Waymarked Trails, Natural Resources Canada and Esri.
