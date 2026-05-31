# TODO - RBAC (Route + Data-level) for OSHAQUE CloudFees

- [x] Implement correct scoping helpers:
  - [x] Student scope: users.email (session) -> students.student_id
  - [x] Parent scope: parent_child.parent_id (session user_id) -> child student_ids
- [x] Implement authorization decorators:
  - [x] require_permission(module_key, perm)
  - [ ] require_route_permissions per role (not required for this task; route permissions handled directly in decorators)
- [x] Add data-level ownership guards (IDOR protection):
  - [x] /collect_fee: ensure target student_id is within logged-in scope
  - [x] /receipt/<payment_id>, /download_receipt_pdf/<payment_id>: ensure payment belongs to scope
  - [x] /payment_history: auto-filter results by scope for student/parent
  - [x] /defaulters: enforce view permissions per matrix and scope as needed
  - [x] /send_reminder/<student_id>, /send_bulk_reminders: admin-only (already partly)
- [x] Apply route-level RBAC to existing routes in current app.py:
  - [x] courses, fee_structure, students, collection, advanced, expenses, users, settings, approvals
- [x] Re-run `python -m py_compile app.py`

