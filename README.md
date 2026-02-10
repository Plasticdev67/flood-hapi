# Flood Hapi

**Egyptian Flood Intelligence Dashboard**
<img width="1896" height="891" alt="image" src="https://github.com/user-attachments/assets/479d7f6d-2184-45af-935c-2763f1262778" />
<img width="1888" height="651" alt="image" src="https://github.com/user-attachments/assets/742fae37-386a-426f-a50c-1f3600418962" />

A free, open-source tool that downloads Environment Agency surface water flood risk data for any UK postcode and exports it as shapefiles.

Enter a postcode, pick a radius, and Flood Hapi fetches all NaFRA2 Risk of Flooding from Surface Water (RoFSW) layers — 3 risk bands and 5 depth bands — clips them to your search area, and packages them as EPSG:27700 shapefiles ready for GIS.

---

## Features

- **One-click setup** — `START.bat` handles Python, dependencies, and launching
- **8 flood data layers** — High/Medium/Low risk bands + 5 depth bands (0.2m to 1.2m)
- **Parallel downloads** — all 6 EA layers fetched simultaneously
- **Shapefile output** — individual `.shp` files per layer in British National Grid (EPSG:27700)
- **WMS map preview** — see the flood extent before downloading
- **Risk gauge** — visual summary of flood risk intensity
- **Dashboard stats** — total cells, active layers, affected area
- **Search history** — recent postcodes saved locally
- **Desktop shortcut** — Hapi icon on your desktop, one click to launch

## Quick Start (Windows)

1. Download or clone this repo
2. Double-click **`START.bat`**
3. That's it

`START.bat` automatically:
- Finds Python (or offers to install it)
- Creates a virtual environment
- Installs all dependencies
- Creates a desktop shortcut
- Starts the server and opens your browser

On second run it skips straight to launching.

## Manual Setup

If you prefer to set up manually:

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/flood-hapi.git
cd flood-hapi

# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run
python app.py
```

Then open http://localhost:5000

## How It Works

1. **Geocode** — converts your UK postcode to BNG coordinates via [postcodes.io](https://postcodes.io)
2. **Download** — fetches raw 2m grid cell vector data from the [Defra Data Services Platform](https://environment.data.gov.uk/) geospatial query API (6 layers in parallel)
3. **Clip** — clips all data to a circular buffer around the postcode centre
4. **Export** — saves each layer as an individual shapefile in EPSG:27700
5. **Package** — zips everything up with metadata for download

## Data Layers

| Layer | Source | Description |
|-------|--------|-------------|
| Risk Band High | NaFRA2 RoFSW | >=3.3% (1 in 30) annual probability |
| Risk Band Medium | NaFRA2 RoFSW | 1%–3.3% (1 in 100 to 1 in 30) |
| Risk Band Low | NaFRA2 RoFSW | 0.1%–1% (1 in 1000 to 1 in 100) |
| Depth 0.2m | NaFRA2 RoFSW | Predicted water depth >= 0.2m |
| Depth 0.3m | NaFRA2 RoFSW | Predicted water depth >= 0.3m |
| Depth 0.6m | NaFRA2 RoFSW | Predicted water depth >= 0.6m |
| Depth 0.9m | NaFRA2 RoFSW | Predicted water depth >= 0.9m |
| Depth 1.2m | NaFRA2 RoFSW | Predicted water depth >= 1.2m |

## Requirements

- Python 3.9+
- Windows (for `.bat` launchers — the Flask app itself runs on any OS)
- Internet connection (to fetch EA data)

### Python Dependencies

- Flask
- requests
- geopandas
- shapely
- fiona
- pyproj

All installed automatically by `START.bat` or `pip install -r requirements.txt`.

## Project Structure

```
flood-hapi/
├── START.bat           # One-click launcher (run this)
├── app.py              # Flask application
├── requirements.txt    # Python dependencies
├── hapi.ico            # Desktop shortcut icon
├── setup.bat           # Manual setup script
├── run.bat             # Manual run script
├── launch.vbs          # Silent launcher (no cmd window)
├── stop.bat            # Stop the server
├── LICENSE             # MIT License
├── static/
│   └── favicon.png     # Browser tab icon
└── templates/
    └── index.html      # Dashboard UI
```

## Troubleshooting

### "Postcode not found"
Make sure you're entering a valid, existing UK postcode. The tool uses postcodes.io for geocoding.

### WMS preview not loading
The EA WMS has a scale threshold of ~1:50,000. For larger radii the preview may not load, but your shapefiles will still be generated correctly.

### "No features returned"
Some areas genuinely have no surface water flood risk data. Try a postcode in a known flood-prone area to verify the tool is working.

### Dependencies fail to install
Fiona and GDAL can be tricky on some systems. On Windows, `pip install -r requirements.txt` should work with Python 3.10+. If you have issues, try `pip install --upgrade pip` first.

## Data Attribution

Contains Environment Agency information &copy; Environment Agency and/or database right.

Flood data sourced from the **NaFRA2 Risk of Flooding from Surface Water (RoFSW)** dataset, available under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

Postcode geocoding via [postcodes.io](https://postcodes.io) (free, open-source).

## License

MIT — see [LICENSE](LICENSE)
