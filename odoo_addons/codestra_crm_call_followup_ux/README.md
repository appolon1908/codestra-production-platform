# Codestra CRM Call Follow-up Workspace — Odoo 19

This optional addon adds the agent-facing workspace and visual polish to the hardened `codestra_crm_call_followup` workflow.

## Why this is separate

The workspace changes forms, list views, kanban behavior, responsive styling, and calls to action. It contains no queue worker, analytics SQL, telephony adapter, or external provider integration, so it can be reviewed and rolled back independently from heavier features.

## Agent experience

- **My Post-call Workspace** kanban, list, calendar, and form action;
- clear customer, call duration, agent, outcome, and next-step summaries;
- primary **Save & Complete** action;
- **Complete & Open Calendar** for callbacks and appointments;
- **Complete Without Email** with explicit confirmation;
- **Complete & Open Customer** for immediate account review;
- related **Customer**, **Opportunity**, and **Calendar** navigation;
- completion guidance that identifies missing outcome, schedule, or email information;
- responsive desktop, tablet, and narrow-browser layout;
- safe fallback to the follow-up record for unmatched calls.

## Form behavior

All completion CTAs call the same hardened core `action_complete()` transaction. The workspace does not duplicate completion logic, bypass row locking, or send mail synchronously.

The workspace does not create a public controller. It respects the core assigned-agent and company record rules.

## Required runtime evidence

- core and workspace addons install and upgrade on a disposable Odoo 19 database;
- inherited views compile against the exact core SHA;
- the modal fits desktop and narrow browser widths without horizontal action loss;
- keyboard shortcuts and visible primary/secondary actions work;
- customer, opportunity, and calendar buttons open the correct records;
- unmatched callers use the safe follow-up fallback;
- complete-without-email creates no mail;
- complete-and-open-calendar creates exactly one event and opens it;
- closing the modal without completion leaves the core action pending;
- accessibility review covers focus order, labels, contrast, keyboard use, and screen-reader names.

No production deployment is authorized until the exact combined SHA has passed these checks and independent review.
