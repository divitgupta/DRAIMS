# DRAIMS: Disaster Resource Allocation and Dynamic Inventory Management System

Mini project for the Database Management Systems lab (CD252IA), Department of Computer Science and Engineering,
RV College of Engineering, Bengaluru. Academic year 2026–27.

DRAIMS tracks disasters and affected zones, donations to warehouses, stock levels and relief requests. Every open
request gets a priority score (damage level, urgency, people affected and waiting time), and allocation serves the
highest score first from the nearest warehouse that has stock. It runs fully offline on a local network.

**Team:** Dev Sisodia, Divit Gupta, Garvit Goyal
**Guide:** Dr Karanam Sunil Kumar, Assistant Professor, Department of CSE, RVCE

## Contents

| Path | What it is |
|---|---|
| `DRAIMS_database.sql` | MySQL script: tables, constraints, function, stored procedures, triggers, views and demo data |
| `draims_app/` | Flask web application with the forms, validation and security ([setup and run](draims_app/README.md)) |
| `diagrams/` | ER diagram, schema, DFD levels 0–2, use case and architecture diagrams |
| `screenshots/` | Screenshots of every form |
| `Synopsis_DBMS_DRAIMS.*` | Synopsis |
| `Report_ReqSpec_ER_DFD_Normalization.*` | Requirement specification, ER diagram, DFD and normalisation report |
| `Diagrams_DBMS_DRAIMS.docx` | All diagrams in one document |
| `Midterm_Report_DBMS_DRAIMS.*` | Midterm report |
| `Checkpoint8_Forms_Security_Validation.*` | Design of forms, security and validation report |

## Quick start

```
mysql -u root -p < DRAIMS_database.sql
mysql -u root -p < draims_app/create_app_user.sql      # change the password in this file first
cd draims_app
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh                                                # then open http://localhost:8000
```

Demo logins: `admin`, `coord.kodagu`, `wm.madikeri`, `fo.kodagu` (password `Relief@2026`).
