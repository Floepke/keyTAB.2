# keyTAB2 Unit Policy

All persisted coordinates and final draw arguments are document millimetres.
`Page.width_mm` and `Page.height_mm` define the physical paper coordinate space.
`System.top_mm`, `System.height_mm`, page margins, and direct `DrawerBase`
dimensions are absolute in that space.

The editor viewport is a raster view of document millimetres. At zoom `z`, it
uses `3.0 * z` raster pixels per document millimetre. Zoom changes only this
view conversion and never changes persisted document geometry.

Engraving appearance values in `Layout` are base millimetres at scale `1.0`.
Their final document size is calculated once through:

$$
\text{final engraving mm} = \text{base mm} \times \text{layout.scale} \times \text{stave.scale}
$$

This intentionally covers staff spacing, notation line widths, dashes,
measure-number placement, and system controls. `Font.size_pt` remains points
until the drawing boundary, where it is converted with `25.4 / 72.0` and the
same engraving scale. `DrawerBase` never applies an implicit scale.

Printed output must use the target printer DPI to convert final document
millimetres to pixels:

$$
\text{pixels per mm} = \frac{\text{printer DPI}}{25.4}
$$