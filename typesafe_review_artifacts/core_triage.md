# Core follow-up triage

Confirmed with regression tests and corrected:

| Area | Correction |
| --- | --- |
| brain | NULL product scope no longer learns from every product. |
| migration | Findings inherit investigation scope before primary-product fallback; repeated duplicate migration does not append repeated notes. |
| feedback | Unicode and meaningful symbol-only text survives normalization; full normalized text distinguishes long complaints sharing a prefix. |
| backlog | Explicit overrides are returned separately from automatic selections; an empty notes mapping clears notes. |
| brief | Resolution rate reuses distinct-case counting, avoiding multiple watches inflating the rate above one. |
| date tools | Six date-filtering tools include the whole date-only upper-bound day while preserving explicit timestamp cutoffs. |
| triage | Model errors defer pending anomalies rather than permanently ignoring them. |
| LLM client | Each request uses the remaining retry timeout budget; JSON repair shares the same deadline. This is not a hard interruption guarantee for a running network request. |
| chat | No exclusivity or concentration claim without corresponding cohort evidence; absent anomaly IDs are not queried. |
| costs API | Month-to-date totals exclude previous months and future dates while preserving lifetime case totals. |

`test_typesafe_core_followup.py` contains 20 focused cases; `test_typesafe_regressions.py` contains 14 initial cases. The final combined backend suite passed 639 tests with one existing development-mode skip.

The raw TypeSafe probabilities are not actionable defect descriptions on their own. These findings were established through local reproductions, code inspection, and offline tests. No claim is made that every remaining flagged context is defect-free. The additional independent core review could not finish due to an agent usage limit; local final diff inspection and full-suite validation completed.
