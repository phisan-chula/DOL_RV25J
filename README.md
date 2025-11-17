
### RV25J Land-Title OCR & Polygon Plotter

This repository provides tools and workflow elements for Thai DOL (Department of Lands) RV25J scanned deeds, including:

Automated OCR extraction pipeline (PP-Structure / PaddleOCR / custom parsing)

Coordinate cleaning & closure validation

*_MAPL1.toml polygon generation

GIS-ready plot visualization (*_plot.png)

Support for UI inspector and interactive viewing

-----------------------------------------------

Example Results

Before – Raw OCR Output (Uncorrected Coordinates)
The initial results produced by the RV25J Application Center after OCR show that several extracted coordinates were inaccurate due to noise and artifacts present in the scanned title deed. As a consequence, the reconstructed parcel polygon becomes highly distorted and does not represent the true land boundary geometry.
![App RV25J P12 Edited](https://raw.githubusercontent.com/phisan-chula/DOL_RV25J/main/App_RV25J_P12_OCR.png)

After – Corrected Coordinates and Replotted Polygon
Following manual review and coordinate correction inside the RV25J Application Center, the parcel was reprocessed and replotted. The corrected coordinates produce a properly closed polygon with an accurate spatial shape that matches the physical land parcel boundary.
![App RV25J P12 Edited](https://raw.githubusercontent.com/phisan-chula/DOL_RV25J/main/App_RV25J_P12_Edited.png)

