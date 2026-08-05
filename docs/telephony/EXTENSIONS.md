# Extension registry

Allocation is 6100-6199 Transportation, 6200-6299 MoneyBee, 6300-6399 Web/AI,
6400-6499 Senior Citizen Products, 6500-6599 Student Repayment, and 6900-6999
Supervisors/QA. Ranges 6600-6899 are rejected by the validation model.

The canonical machine-readable registry is `config/extension-registry.json`.
Extension 6101 is reserved for the isolated telephony lab and cannot transfer
or route externally. Duplicate extension records are rejected during registry
loading/reconciliation.

