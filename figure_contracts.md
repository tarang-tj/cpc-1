# Figure contracts — CPC-1 synthetic contract benchmark

All figures use designed, provenance-tagged synthetic fixtures (`synthetic:contract-v1`). They demonstrate implementation contract behavior only; they do not estimate real-world safety, quality, or latency.

| Figure family | Core conclusion | Evidence | Chart type | Export |
|---|---|---|---|---|
| `raw_q*_fixture_composition` | Each task family includes balanced ACT/ASK/REJECT fixture outcomes. | Fixture counts per task. | Categorical bar chart; y-axis begins at zero. | SVG + 300-DPI PNG |
| `process_q*_mutation_coverage` | Each task family has five certificate-forgery classes exercised. | Mutation test inventory. | Dot plot; direct categories, no false continuity claim. | SVG + 300-DPI PNG |
| `result_q*_decision_agreement` | CPC-1 agrees with the designed contract rule on all synthetic fixtures; blind action does not. | Rule-defined labels vs policy decisions. | Categorical bar chart; y-axis begins at zero. | SVG + 300-DPI PNG |

Visual safeguards: colorblind-safe Okabe–Ito colors, editable SVG text, no dual axes, no pie/3D charts, and grayscale previews. The result bars are not statistical estimates: no error bars or significance tests are appropriate because the fixtures are deterministic.
