# ArmySynthdatagenerator (SOAP)

**A Synthea-style state-machine synthetic data generator for U.S. Army operations.**

---

## What We Are Doing (In Plain English)

In defense and federal data engineering projects, engineers cannot use real military data in development or testing environments because it is sensitive or classified. However, standard fake-data tools (like `Faker`) just generate random, disconnected rows of text and numbers—which makes it impossible to test real data pipelines, joins, or historical trends.

**ArmySynthdatagenerator** solves this by taking the architectural approach of **Synthea** (a famous open-source state-machine simulator) and applying it strictly to **U.S. Army operations**. Instead of generating random rows, it simulates a living Army brigade day-by-day over time.

---

## How We Are Doing It

### 1. Three Living Entities Simulated Over Time
We start with an **Armored Brigade Combat Team (ABCT)** and track three connected groups day-by-day:
* **Units:** Corps $\rightarrow$ Division $\rightarrow$ Brigade $\rightarrow$ Battalions $\rightarrow$ Companies, each with an authorized list of positions and gear (**FMSWeb**).
* **Soldiers:** Enlisted soldiers, warrant officers, and officers with specific job codes (like `19K` Tank Crewman or `91A` Tank Mechanic) assigned to slots in those units (**IPPS-A**).
* **Equipment:** Individual serialized tanks (`M1A2 Abrams`), fighting vehicles (`M2A4 Bradley`), howitzers (`M109A7 Paladin`), trucks (`JLTV`, `FMTV`), and tactical radios (**GCSS-Army**).

### 2. JSON State Machines Drive Every Event
Every Unit, Soldier, and piece of Equipment moves through a **flowchart (finite state machine)** defined in simple JSON files (`soap/modules/*.json`):
* **Equipment Lifecycle:** A tank starts *Fully Mission Capable (`FMC`)* $\rightarrow$ logs operating hours $\rightarrow$ undergoes inspection $\rightarrow$ breaks down (*Not Mission Capable - Supply, `NMCS`*) $\rightarrow$ opens a maintenance work order $\rightarrow$ orders a spare part (e.g., turbine engine or thermal sight) $\rightarrow$ triggers a financial budget obligation (**GFEBS**) $\rightarrow$ waits 3–14 days for shipping $\rightarrow$ gets repaired by a unit mechanic $\rightarrow$ returns to `FMC`.
* **Soldier Lifecycle:** A soldier reports to their unit $\rightarrow$ completes rifle qualification (**DTMS**) $\rightarrow$ rotates through the National Training Center (NTC) $\rightarrow$ gets promoted when eligible $\rightarrow$ transfers units (PCS) or finishes their contract (ETS).
* **Unit Readiness Lifecycle:** Every 30 days, each unit conducts collective training and calculates its monthly readiness score (**NetUSR** `C-1` through `C-4`) based on how many of its soldiers are deployable and how many of its vehicles are working right now.

### 3. Connected Data Across 5 Army Systems
Because one simulation clock drives everything, all 11 output tables match up across systems:
* When a tank breaks down in **GCSS-Army**, the mechanic assigned to fix it is a real `91A` soldier from **IPPS-A**, the spare part ordered bills the unit's budget in **GFEBS**, and the broken tank lowers the company's monthly readiness rating in **NetUSR**.

---

## Quick Start

```bash
# Inspect the JSON state machines
python3 -m soap.cli modules

# Generate 180 days of synthetic Army data (CSV & JSONL)
python3 -m soap.cli generate --days 180 --scale 0.25 --output-dir ./output
```
