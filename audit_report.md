# Dataset audit: .

Score: 9/12 checks passed

| Result | Check | Detail |
| --- | --- | --- |
| INFO | Size | 15 nodes, 20 road segments |
| PASS | Edges reference existing nodes | 0 bad |
| PASS | No self-loops | 0 found |
| PASS | No duplicate segments | 0 duplicates |
| PASS | All nodes inside Ulaanbaatar bounding box | 0 outside |
| WARN | Lengths are estimated (straight line x 1.3), not measured | no length_km column |
| PASS | Speed limits in 10-120 km/h | 0 outliers, range 40-70 |
| PASS | Congestion within 0-1 | mean 0.55 |
| WARN | Congestion comes from real measurements | synthetic / assumed (no real traffic data) |
| WARN | Road class (highway) recorded | missing: cannot vary congestion by road type |
| PASS | Graph strongly connected (every place can reach every place) | largest component 15/15 nodes (100%), 1 components |
| PASS | Alternative routes exist (independent cycles >= 30% of nodes) | 6 cycles for 15 nodes (0.40 per node) |
| PASS | Few dead-end nodes (<= 15%) | 2 dead ends (13%) |
| INFO | One-way segments | 2/20 (10%) |
| INFO | Closed segments | 1 |
