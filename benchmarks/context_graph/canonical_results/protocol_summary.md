# Protocol Benchmark Summary

Tokenizer: `tiktoken:cl100k_base`

| Corpus | Strategy | Avg tokens | Node recall | Edge recall | Path recall | Irrelevant ratio | Latency ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| medium_sparse | bm25_markdown | 80.2 | 0.393 | 0.167 | 0.900 | 0.146 | 21.386 |
| medium_sparse | full_markdown | 109177.0 | 1.000 | 1.000 | 1.000 | 0.996 | 2.774 |
| medium_sparse | graph_1hop | 176.2 | 0.862 | 0.792 | 0.967 | 0.326 | 22.628 |
| medium_sparse | graph_1hop_gg_max | 109.2 | 0.862 | 0.792 | 0.967 | 0.326 | 16.439 |
| medium_sparse | graph_1hop_gg_max_hybrid | 452.0 | 0.862 | 0.792 | 0.967 | 0.326 | 23.964 |
| medium_sparse | graph_1hop_lowlevel | 156.7 | 0.862 | 0.792 | 0.967 | 0.326 | 20.306 |
| medium_sparse | graph_1hop_semantic_arrow | 118.8 | 0.862 | 0.792 | 0.967 | 0.326 | 18.575 |
| medium_sparse | graph_1hop_sql | 177.5 | 0.862 | 0.792 | 0.967 | 0.326 | 21.290 |
| medium_sparse | graph_2hop | 505.8 | 1.000 | 1.000 | 1.000 | 0.625 | 21.562 |
| medium_sparse | graph_2hop_gg_max | 273.0 | 1.000 | 1.000 | 1.000 | 0.625 | 23.698 |
| medium_sparse | graph_2hop_gg_max_hybrid | 1171.8 | 1.000 | 1.000 | 1.000 | 0.625 | 19.816 |
| medium_sparse | graph_2hop_lowlevel | 382.0 | 1.000 | 1.000 | 1.000 | 0.625 | 18.892 |
| medium_sparse | graph_2hop_semantic_arrow | 356.3 | 1.000 | 1.000 | 1.000 | 0.625 | 19.457 |
| medium_sparse | graph_2hop_sql | 493.2 | 1.000 | 1.000 | 1.000 | 0.625 | 24.426 |
| medium_sparse | graph_keyword_hybrid | 597.8 | 0.862 | 0.792 | 0.967 | 0.359 | 35.335 |
| medium_sparse | hierarchical_summary | 52.5 | 0.393 | 0.167 | 0.900 | 0.139 | 22.557 |
| medium_sparse | keyword_markdown | 97.0 | 0.421 | 0.200 | 0.900 | 0.125 | 16.989 |
| small_dense | bm25_markdown | 80.2 | 0.389 | 0.167 | 0.900 | 0.146 | 1.075 |
| small_dense | full_markdown | 8149.0 | 1.000 | 1.000 | 1.000 | 0.931 | 0.320 |
| small_dense | graph_1hop | 237.2 | 0.856 | 0.787 | 0.967 | 0.470 | 1.109 |
| small_dense | graph_1hop_gg_max | 138.5 | 0.856 | 0.787 | 0.967 | 0.470 | 1.280 |
| small_dense | graph_1hop_gg_max_hybrid | 592.7 | 0.856 | 0.787 | 0.967 | 0.470 | 1.177 |
| small_dense | graph_1hop_lowlevel | 197.0 | 0.856 | 0.787 | 0.967 | 0.470 | 1.014 |
| small_dense | graph_1hop_semantic_arrow | 162.3 | 0.856 | 0.787 | 0.967 | 0.470 | 1.324 |
| small_dense | graph_1hop_sql | 236.5 | 0.856 | 0.787 | 0.967 | 0.470 | 1.063 |
| small_dense | graph_2hop | 854.7 | 1.000 | 1.000 | 1.000 | 0.708 | 1.270 |
| small_dense | graph_2hop_gg_max | 456.0 | 1.000 | 1.000 | 1.000 | 0.708 | 1.102 |
| small_dense | graph_2hop_gg_max_hybrid | 1877.7 | 1.000 | 1.000 | 1.000 | 0.708 | 1.267 |
| small_dense | graph_2hop_lowlevel | 630.5 | 1.000 | 1.000 | 1.000 | 0.708 | 1.032 |
| small_dense | graph_2hop_semantic_arrow | 622.3 | 1.000 | 1.000 | 1.000 | 0.708 | 1.068 |
| small_dense | graph_2hop_sql | 827.3 | 1.000 | 1.000 | 1.000 | 0.708 | 1.151 |
| small_dense | graph_keyword_hybrid | 861.0 | 0.856 | 0.787 | 0.967 | 0.503 | 2.019 |
| small_dense | hierarchical_summary | 52.5 | 0.389 | 0.167 | 0.900 | 0.139 | 1.128 |
| small_dense | keyword_markdown | 94.5 | 0.389 | 0.167 | 0.900 | 0.146 | 0.914 |
| small_sparse | bm25_markdown | 79.2 | 0.439 | 0.167 | 0.900 | 0.146 | 0.927 |
| small_sparse | full_markdown | 7054.0 | 1.000 | 1.000 | 1.000 | 0.954 | 0.133 |
| small_sparse | graph_1hop | 145.7 | 0.900 | 0.817 | 0.967 | 0.313 | 0.944 |
| small_sparse | graph_1hop_gg_max | 94.2 | 0.900 | 0.817 | 0.967 | 0.313 | 1.008 |
| small_sparse | graph_1hop_gg_max_hybrid | 386.0 | 0.900 | 0.817 | 0.967 | 0.313 | 0.883 |
| small_sparse | graph_1hop_lowlevel | 136.2 | 0.900 | 0.817 | 0.967 | 0.313 | 1.038 |
| small_sparse | graph_1hop_semantic_arrow | 97.2 | 0.900 | 0.817 | 0.967 | 0.313 | 0.893 |
| small_sparse | graph_1hop_sql | 148.3 | 0.900 | 0.817 | 0.967 | 0.313 | 0.853 |
| small_sparse | graph_2hop | 298.2 | 1.000 | 1.000 | 1.000 | 0.491 | 0.920 |
| small_sparse | graph_2hop_gg_max | 172.0 | 1.000 | 1.000 | 1.000 | 0.491 | 1.008 |
| small_sparse | graph_2hop_gg_max_hybrid | 703.7 | 1.000 | 1.000 | 1.000 | 0.491 | 0.894 |
| small_sparse | graph_2hop_lowlevel | 243.5 | 1.000 | 1.000 | 1.000 | 0.491 | 0.889 |
| small_sparse | graph_2hop_semantic_arrow | 210.5 | 1.000 | 1.000 | 1.000 | 0.491 | 1.264 |
| small_sparse | graph_2hop_sql | 294.5 | 1.000 | 1.000 | 1.000 | 0.491 | 1.064 |
| small_sparse | graph_keyword_hybrid | 539.0 | 0.900 | 0.817 | 0.967 | 0.351 | 1.784 |
| small_sparse | hierarchical_summary | 52.5 | 0.439 | 0.167 | 0.900 | 0.139 | 0.984 |
| small_sparse | keyword_markdown | 94.5 | 0.439 | 0.167 | 0.900 | 0.146 | 0.846 |
| tiny_sparse | bm25_markdown | 94.0 | 0.572 | 0.333 | 0.900 | 0.104 | 0.289 |
| tiny_sparse | full_markdown | 943.0 | 1.000 | 1.000 | 1.000 | 0.722 | 0.041 |
| tiny_sparse | graph_1hop | 128.5 | 0.900 | 0.817 | 0.967 | 0.322 | 0.224 |
| tiny_sparse | graph_1hop_gg_max | 86.3 | 0.900 | 0.817 | 0.967 | 0.322 | 0.269 |
| tiny_sparse | graph_1hop_gg_max_hybrid | 341.3 | 0.900 | 0.817 | 0.967 | 0.322 | 0.215 |
| tiny_sparse | graph_1hop_lowlevel | 125.8 | 0.900 | 0.817 | 0.967 | 0.322 | 0.206 |
| tiny_sparse | graph_1hop_semantic_arrow | 86.3 | 0.900 | 0.817 | 0.967 | 0.322 | 0.170 |
| tiny_sparse | graph_1hop_sql | 131.7 | 0.900 | 0.817 | 0.967 | 0.322 | 0.180 |
| tiny_sparse | graph_2hop | 225.3 | 1.000 | 1.000 | 1.000 | 0.491 | 0.208 |
| tiny_sparse | graph_2hop_gg_max | 138.0 | 1.000 | 1.000 | 1.000 | 0.491 | 0.204 |
| tiny_sparse | graph_2hop_gg_max_hybrid | 526.3 | 1.000 | 1.000 | 1.000 | 0.491 | 0.223 |
| tiny_sparse | graph_2hop_lowlevel | 197.5 | 1.000 | 1.000 | 1.000 | 0.491 | 0.212 |
| tiny_sparse | graph_2hop_semantic_arrow | 162.3 | 1.000 | 1.000 | 1.000 | 0.491 | 0.214 |
| tiny_sparse | graph_2hop_sql | 223.8 | 1.000 | 1.000 | 1.000 | 0.491 | 0.207 |
| tiny_sparse | graph_keyword_hybrid | 356.7 | 0.900 | 0.817 | 0.967 | 0.328 | 0.401 |
| tiny_sparse | hierarchical_summary | 69.5 | 0.572 | 0.333 | 0.900 | 0.083 | 0.231 |
| tiny_sparse | keyword_markdown | 94.0 | 0.572 | 0.333 | 0.900 | 0.104 | 0.273 |

## Query Class Breakdown

| Query class | Strategy | Avg tokens | Node recall | Edge recall | Path recall | Irrelevant ratio |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| blast_radius | bm25_markdown | 31.0 | 0.148 | 0.000 | 1.000 | 0.000 |
| blast_radius | full_markdown | 31330.8 | 1.000 | 1.000 | 1.000 | 0.832 |
| blast_radius | graph_1hop | 94.8 | 0.477 | 0.318 | 1.000 | 0.000 |
| blast_radius | graph_1hop_gg_max | 72.0 | 0.477 | 0.318 | 1.000 | 0.000 |
| blast_radius | graph_1hop_gg_max_hybrid | 253.5 | 0.477 | 0.318 | 1.000 | 0.000 |
| blast_radius | graph_1hop_lowlevel | 105.0 | 0.477 | 0.318 | 1.000 | 0.000 |
| blast_radius | graph_1hop_semantic_arrow | 64.8 | 0.477 | 0.318 | 1.000 | 0.000 |
| blast_radius | graph_1hop_sql | 99.2 | 0.477 | 0.318 | 1.000 | 0.000 |
| blast_radius | graph_2hop | 270.0 | 1.000 | 1.000 | 1.000 | 0.000 |
| blast_radius | graph_2hop_gg_max | 161.5 | 1.000 | 1.000 | 1.000 | 0.000 |
| blast_radius | graph_2hop_gg_max_hybrid | 617.5 | 1.000 | 1.000 | 1.000 | 0.000 |
| blast_radius | graph_2hop_lowlevel | 228.2 | 1.000 | 1.000 | 1.000 | 0.000 |
| blast_radius | graph_2hop_semantic_arrow | 195.5 | 1.000 | 1.000 | 1.000 | 0.000 |
| blast_radius | graph_2hop_sql | 267.0 | 1.000 | 1.000 | 1.000 | 0.000 |
| blast_radius | graph_keyword_hybrid | 247.2 | 0.477 | 0.318 | 1.000 | 0.000 |
| blast_radius | hierarchical_summary | 29.0 | 0.148 | 0.000 | 1.000 | 0.000 |
| blast_radius | keyword_markdown | 31.0 | 0.148 | 0.000 | 1.000 | 0.000 |
| direct_lookup | bm25_markdown | 31.0 | 0.333 | 0.000 | 1.000 | 0.000 |
| direct_lookup | full_markdown | 31330.8 | 1.000 | 1.000 | 1.000 | 0.918 |
| direct_lookup | graph_1hop | 94.8 | 1.000 | 1.000 | 1.000 | 0.100 |
| direct_lookup | graph_1hop_gg_max | 72.0 | 1.000 | 1.000 | 1.000 | 0.100 |
| direct_lookup | graph_1hop_gg_max_hybrid | 253.5 | 1.000 | 1.000 | 1.000 | 0.100 |
| direct_lookup | graph_1hop_lowlevel | 105.0 | 1.000 | 1.000 | 1.000 | 0.100 |
| direct_lookup | graph_1hop_semantic_arrow | 64.8 | 1.000 | 1.000 | 1.000 | 0.100 |
| direct_lookup | graph_1hop_sql | 99.2 | 1.000 | 1.000 | 1.000 | 0.100 |
| direct_lookup | graph_2hop | 270.0 | 1.000 | 1.000 | 1.000 | 0.556 |
| direct_lookup | graph_2hop_gg_max | 161.5 | 1.000 | 1.000 | 1.000 | 0.556 |
| direct_lookup | graph_2hop_gg_max_hybrid | 617.5 | 1.000 | 1.000 | 1.000 | 0.556 |
| direct_lookup | graph_2hop_lowlevel | 228.2 | 1.000 | 1.000 | 1.000 | 0.556 |
| direct_lookup | graph_2hop_semantic_arrow | 195.5 | 1.000 | 1.000 | 1.000 | 0.556 |
| direct_lookup | graph_2hop_sql | 267.0 | 1.000 | 1.000 | 1.000 | 0.556 |
| direct_lookup | graph_keyword_hybrid | 247.2 | 1.000 | 1.000 | 1.000 | 0.100 |
| direct_lookup | hierarchical_summary | 29.0 | 0.333 | 0.000 | 1.000 | 0.000 |
| direct_lookup | keyword_markdown | 31.0 | 0.333 | 0.000 | 1.000 | 0.000 |
| multi_hop_path | bm25_markdown | 57.0 | 0.400 | 0.000 | 0.400 | 0.000 |
| multi_hop_path | full_markdown | 31330.8 | 1.000 | 1.000 | 1.000 | 0.864 |
| multi_hop_path | graph_1hop | 200.5 | 0.800 | 0.500 | 0.800 | 0.442 |
| multi_hop_path | graph_1hop_gg_max | 120.0 | 0.800 | 0.500 | 0.800 | 0.442 |
| multi_hop_path | graph_1hop_gg_max_hybrid | 520.0 | 0.800 | 0.500 | 0.800 | 0.442 |
| multi_hop_path | graph_1hop_lowlevel | 174.0 | 0.800 | 0.500 | 0.800 | 0.442 |
| multi_hop_path | graph_1hop_semantic_arrow | 137.8 | 0.800 | 0.500 | 0.800 | 0.442 |
| multi_hop_path | graph_1hop_sql | 201.0 | 0.800 | 0.500 | 0.800 | 0.442 |
| multi_hop_path | graph_2hop | 577.8 | 1.000 | 1.000 | 1.000 | 0.616 |
| multi_hop_path | graph_2hop_gg_max | 317.0 | 1.000 | 1.000 | 1.000 | 0.616 |
| multi_hop_path | graph_2hop_gg_max_hybrid | 1277.5 | 1.000 | 1.000 | 1.000 | 0.616 |
| multi_hop_path | graph_2hop_lowlevel | 443.0 | 1.000 | 1.000 | 1.000 | 0.616 |
| multi_hop_path | graph_2hop_semantic_arrow | 423.0 | 1.000 | 1.000 | 1.000 | 0.616 |
| multi_hop_path | graph_2hop_sql | 561.0 | 1.000 | 1.000 | 1.000 | 0.616 |
| multi_hop_path | graph_keyword_hybrid | 537.8 | 0.800 | 0.500 | 0.800 | 0.442 |
| multi_hop_path | hierarchical_summary | 54.0 | 0.400 | 0.000 | 0.400 | 0.000 |
| multi_hop_path | keyword_markdown | 57.0 | 0.400 | 0.000 | 0.400 | 0.000 |
| negative_query | bm25_markdown | 62.5 | 1.000 | 1.000 | 1.000 | 0.000 |
| negative_query | full_markdown | 31330.8 | 1.000 | 1.000 | 1.000 | 0.945 |
| negative_query | graph_1hop | 180.5 | 1.000 | 1.000 | 1.000 | 0.678 |
| negative_query | graph_1hop_gg_max | 109.8 | 1.000 | 1.000 | 1.000 | 0.678 |
| negative_query | graph_1hop_gg_max_hybrid | 473.5 | 1.000 | 1.000 | 1.000 | 0.678 |
| negative_query | graph_1hop_lowlevel | 157.8 | 1.000 | 1.000 | 1.000 | 0.678 |
| negative_query | graph_1hop_semantic_arrow | 119.8 | 1.000 | 1.000 | 1.000 | 0.678 |
| negative_query | graph_1hop_sql | 182.5 | 1.000 | 1.000 | 1.000 | 0.678 |
| negative_query | graph_2hop | 502.5 | 1.000 | 1.000 | 1.000 | 0.842 |
| negative_query | graph_2hop_gg_max | 271.5 | 1.000 | 1.000 | 1.000 | 0.842 |
| negative_query | graph_2hop_gg_max_hybrid | 1165.8 | 1.000 | 1.000 | 1.000 | 0.842 |
| negative_query | graph_2hop_lowlevel | 380.2 | 1.000 | 1.000 | 1.000 | 0.842 |
| negative_query | graph_2hop_semantic_arrow | 355.0 | 1.000 | 1.000 | 1.000 | 0.842 |
| negative_query | graph_2hop_sql | 489.8 | 1.000 | 1.000 | 1.000 | 0.842 |
| negative_query | graph_keyword_hybrid | 483.5 | 1.000 | 1.000 | 1.000 | 0.678 |
| negative_query | hierarchical_summary | 57.5 | 1.000 | 1.000 | 1.000 | 0.000 |
| negative_query | keyword_markdown | 62.5 | 1.000 | 1.000 | 1.000 | 0.000 |
| reverse_lookup | bm25_markdown | 31.0 | 0.417 | 0.000 | 1.000 | 0.000 |
| reverse_lookup | full_markdown | 31330.8 | 1.000 | 1.000 | 1.000 | 0.942 |
| reverse_lookup | graph_1hop | 103.5 | 1.000 | 1.000 | 1.000 | 0.329 |
| reverse_lookup | graph_1hop_gg_max | 76.0 | 1.000 | 1.000 | 1.000 | 0.329 |
| reverse_lookup | graph_1hop_gg_max_hybrid | 273.0 | 1.000 | 1.000 | 1.000 | 0.329 |
| reverse_lookup | graph_1hop_lowlevel | 110.5 | 1.000 | 1.000 | 1.000 | 0.329 |
| reverse_lookup | graph_1hop_semantic_arrow | 70.5 | 1.000 | 1.000 | 1.000 | 0.329 |
| reverse_lookup | graph_1hop_sql | 108.2 | 1.000 | 1.000 | 1.000 | 0.329 |
| reverse_lookup | graph_2hop | 280.2 | 1.000 | 1.000 | 1.000 | 0.650 |
| reverse_lookup | graph_2hop_gg_max | 166.5 | 1.000 | 1.000 | 1.000 | 0.650 |
| reverse_lookup | graph_2hop_gg_max_hybrid | 641.5 | 1.000 | 1.000 | 1.000 | 0.650 |
| reverse_lookup | graph_2hop_lowlevel | 234.8 | 1.000 | 1.000 | 1.000 | 0.650 |
| reverse_lookup | graph_2hop_semantic_arrow | 202.0 | 1.000 | 1.000 | 1.000 | 0.650 |
| reverse_lookup | graph_2hop_sql | 277.0 | 1.000 | 1.000 | 1.000 | 0.650 |
| reverse_lookup | graph_keyword_hybrid | 268.5 | 1.000 | 1.000 | 1.000 | 0.329 |
| reverse_lookup | hierarchical_summary | 29.0 | 0.417 | 0.000 | 1.000 | 0.000 |
| reverse_lookup | keyword_markdown | 31.0 | 0.417 | 0.000 | 1.000 | 0.000 |
| subsystem_summary | bm25_markdown | 287.8 | 0.392 | 0.250 | 1.000 | 0.812 |
| subsystem_summary | full_markdown | 31330.8 | 1.000 | 1.000 | 1.000 | 0.905 |
| subsystem_summary | graph_1hop | 357.2 | 1.000 | 1.000 | 1.000 | 0.598 |
| subsystem_summary | graph_1hop_gg_max | 192.5 | 1.000 | 1.000 | 1.000 | 0.598 |
| subsystem_summary | graph_1hop_gg_max_hybrid | 884.5 | 1.000 | 1.000 | 1.000 | 0.598 |
| subsystem_summary | graph_1hop_lowlevel | 271.2 | 1.000 | 1.000 | 1.000 | 0.598 |
| subsystem_summary | graph_1hop_semantic_arrow | 239.5 | 1.000 | 1.000 | 1.000 | 0.598 |
| subsystem_summary | graph_1hop_sql | 350.8 | 1.000 | 1.000 | 1.000 | 0.598 |
| subsystem_summary | graph_2hop | 925.5 | 1.000 | 1.000 | 1.000 | 0.807 |
| subsystem_summary | graph_2hop_gg_max | 480.5 | 1.000 | 1.000 | 1.000 | 0.807 |
| subsystem_summary | graph_2hop_gg_max_hybrid | 2099.5 | 1.000 | 1.000 | 1.000 | 0.807 |
| subsystem_summary | graph_2hop_lowlevel | 665.8 | 1.000 | 1.000 | 1.000 | 0.807 |
| subsystem_summary | graph_2hop_semantic_arrow | 656.2 | 1.000 | 1.000 | 1.000 | 0.807 |
| subsystem_summary | graph_2hop_sql | 896.5 | 1.000 | 1.000 | 1.000 | 0.807 |
| subsystem_summary | graph_keyword_hybrid | 1747.5 | 1.000 | 1.000 | 1.000 | 0.763 |
| subsystem_summary | hierarchical_summary | 142.0 | 0.392 | 0.250 | 1.000 | 0.750 |
| subsystem_summary | keyword_markdown | 357.5 | 0.433 | 0.300 | 1.000 | 0.781 |

## Threshold Check

| Corpus | Strategy | Status | Reason |
| --- | --- | --- | --- |
| medium_sparse | bm25_markdown | FAIL | node_recall 0.393 < 0.75; edge_recall 0.167 < 0.65 |
| medium_sparse | full_markdown | FAIL | irrelevant 0.996 > 0.85 |
| medium_sparse | graph_1hop | PASS | meets configured thresholds |
| medium_sparse | graph_1hop_gg_max | PASS | meets configured thresholds |
| medium_sparse | graph_1hop_gg_max_hybrid | PASS | meets configured thresholds |
| medium_sparse | graph_1hop_lowlevel | PASS | meets configured thresholds |
| medium_sparse | graph_1hop_semantic_arrow | PASS | meets configured thresholds |
| medium_sparse | graph_1hop_sql | PASS | meets configured thresholds |
| medium_sparse | graph_2hop | PASS | meets configured thresholds |
| medium_sparse | graph_2hop_gg_max | PASS | meets configured thresholds |
| medium_sparse | graph_2hop_gg_max_hybrid | PASS | meets configured thresholds |
| medium_sparse | graph_2hop_lowlevel | PASS | meets configured thresholds |
| medium_sparse | graph_2hop_semantic_arrow | PASS | meets configured thresholds |
| medium_sparse | graph_2hop_sql | PASS | meets configured thresholds |
| medium_sparse | graph_keyword_hybrid | PASS | meets configured thresholds |
| medium_sparse | hierarchical_summary | FAIL | node_recall 0.393 < 0.75; edge_recall 0.167 < 0.65 |
| medium_sparse | keyword_markdown | FAIL | node_recall 0.421 < 0.75; edge_recall 0.200 < 0.65 |
| small_dense | bm25_markdown | FAIL | node_recall 0.389 < 0.75; edge_recall 0.167 < 0.65 |
| small_dense | full_markdown | FAIL | irrelevant 0.931 > 0.85 |
| small_dense | graph_1hop | PASS | meets configured thresholds |
| small_dense | graph_1hop_gg_max | PASS | meets configured thresholds |
| small_dense | graph_1hop_gg_max_hybrid | PASS | meets configured thresholds |
| small_dense | graph_1hop_lowlevel | PASS | meets configured thresholds |
| small_dense | graph_1hop_semantic_arrow | PASS | meets configured thresholds |
| small_dense | graph_1hop_sql | PASS | meets configured thresholds |
| small_dense | graph_2hop | PASS | meets configured thresholds |
| small_dense | graph_2hop_gg_max | PASS | meets configured thresholds |
| small_dense | graph_2hop_gg_max_hybrid | PASS | meets configured thresholds |
| small_dense | graph_2hop_lowlevel | PASS | meets configured thresholds |
| small_dense | graph_2hop_semantic_arrow | PASS | meets configured thresholds |
| small_dense | graph_2hop_sql | PASS | meets configured thresholds |
| small_dense | graph_keyword_hybrid | PASS | meets configured thresholds |
| small_dense | hierarchical_summary | FAIL | node_recall 0.389 < 0.75; edge_recall 0.167 < 0.65 |
| small_dense | keyword_markdown | FAIL | node_recall 0.389 < 0.75; edge_recall 0.167 < 0.65 |
| small_sparse | bm25_markdown | FAIL | node_recall 0.439 < 0.75; edge_recall 0.167 < 0.65 |
| small_sparse | full_markdown | FAIL | irrelevant 0.954 > 0.85 |
| small_sparse | graph_1hop | PASS | meets configured thresholds |
| small_sparse | graph_1hop_gg_max | PASS | meets configured thresholds |
| small_sparse | graph_1hop_gg_max_hybrid | PASS | meets configured thresholds |
| small_sparse | graph_1hop_lowlevel | PASS | meets configured thresholds |
| small_sparse | graph_1hop_semantic_arrow | PASS | meets configured thresholds |
| small_sparse | graph_1hop_sql | PASS | meets configured thresholds |
| small_sparse | graph_2hop | PASS | meets configured thresholds |
| small_sparse | graph_2hop_gg_max | PASS | meets configured thresholds |
| small_sparse | graph_2hop_gg_max_hybrid | PASS | meets configured thresholds |
| small_sparse | graph_2hop_lowlevel | PASS | meets configured thresholds |
| small_sparse | graph_2hop_semantic_arrow | PASS | meets configured thresholds |
| small_sparse | graph_2hop_sql | PASS | meets configured thresholds |
| small_sparse | graph_keyword_hybrid | PASS | meets configured thresholds |
| small_sparse | hierarchical_summary | FAIL | node_recall 0.439 < 0.75; edge_recall 0.167 < 0.65 |
| small_sparse | keyword_markdown | FAIL | node_recall 0.439 < 0.75; edge_recall 0.167 < 0.65 |
| tiny_sparse | bm25_markdown | FAIL | node_recall 0.572 < 0.75; edge_recall 0.333 < 0.65 |
| tiny_sparse | full_markdown | PASS | meets configured thresholds |
| tiny_sparse | graph_1hop | PASS | meets configured thresholds |
| tiny_sparse | graph_1hop_gg_max | PASS | meets configured thresholds |
| tiny_sparse | graph_1hop_gg_max_hybrid | PASS | meets configured thresholds |
| tiny_sparse | graph_1hop_lowlevel | PASS | meets configured thresholds |
| tiny_sparse | graph_1hop_semantic_arrow | PASS | meets configured thresholds |
| tiny_sparse | graph_1hop_sql | PASS | meets configured thresholds |
| tiny_sparse | graph_2hop | PASS | meets configured thresholds |
| tiny_sparse | graph_2hop_gg_max | PASS | meets configured thresholds |
| tiny_sparse | graph_2hop_gg_max_hybrid | PASS | meets configured thresholds |
| tiny_sparse | graph_2hop_lowlevel | PASS | meets configured thresholds |
| tiny_sparse | graph_2hop_semantic_arrow | PASS | meets configured thresholds |
| tiny_sparse | graph_2hop_sql | PASS | meets configured thresholds |
| tiny_sparse | graph_keyword_hybrid | PASS | meets configured thresholds |
| tiny_sparse | hierarchical_summary | FAIL | node_recall 0.572 < 0.75; edge_recall 0.333 < 0.65 |
| tiny_sparse | keyword_markdown | FAIL | node_recall 0.572 < 0.75; edge_recall 0.333 < 0.65 |

Artifacts:
- CSV: `out\protocol\protocol_results.csv`
- Saved context packets: `out\protocol\packets`
- Saved prompts: `out\protocol\saved_prompts.jsonl`