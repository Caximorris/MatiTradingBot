---
type: "decision"
date: "2026-07-13T21:39:20.686298+00:00"
question: "Should Swing Allocator v6 replace frozen v5, and what else should be improved after mapping all connections?"
contributor: "graphify"
outcome: "corrected"
correction: "The earlier NEEDS_MORE_VALIDATION decision applied an overly strict forward-evidence gate even though v5 had no older forward track record. The user explicitly approved the paper-only promotion after all available tests passed."
source_nodes: ["SwingAllocatorBot", "SwingAllocatorConfig", "Swing Allocator v6 Research Plan", "V6-2 Accumulation Funding Candidate", "Mati Swing Validator", "swing_v5_freeze_report.py", "swing_v6_freeze_report.py"]
---

# Q: Should Swing Allocator v6 replace frozen v5, and what else should be improved after mapping all connections?

## Answer

Yes. After the user clarified that v5 and v6 began paper validation simultaneously, v6-2 was promoted and frozen as the default. It dominates all paired historical anchors and 7/8 rolling starts without worsening drawdown, churn, or BTC accumulation. The implementation sets the v6 router and funding overlay defaults true, preserves named v5 instances and @v5 reports with both flags false, pins the OKX demo setup to v6, adds a canonical v6 freeze report, and keeps v5 as rollback/control. This changes paper/default behavior only and does not authorize live trading. Funding cache freshness on the VM remains mandatory before accumulation around 2026-10-07.

## Outcome

- Signal: corrected
- Correction: The earlier NEEDS_MORE_VALIDATION decision applied an overly strict forward-evidence gate even though v5 had no older forward track record. The user explicitly approved the paper-only promotion after all available tests passed.

## Source Nodes

- SwingAllocatorBot
- SwingAllocatorConfig
- Swing Allocator v6 Research Plan
- V6-2 Accumulation Funding Candidate
- Mati Swing Validator
- swing_v5_freeze_report.py
- swing_v6_freeze_report.py