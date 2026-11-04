"""
Authentic U.S. Army Reference Data Catalogs for SOAP.
Strictly military operational, personnel, logistics, training, and financial metadata.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class UnitDefinition:
    uic: str
    parent_uic: Optional[str]
    unit_name: str
    echelon: str  # CORPS, DIV, BDE, BN, CO
    unit_type: str  # ABCT, INF_BN, CAB_CO, BSB, etc.
    home_station: str
    dodaac: str
    fund_center: str
    auth_personnel: int


@dataclass(frozen=True)
class RankDefinition:
    pay_grade: str
    rank_code: str
    title: str
    category: str  # ENLISTED, WARRANT, OFFICER
    min_tis_months: int
    min_tig_months: int
    base_pay_monthly: float


@dataclass(frozen=True)
class MOSDefinition:
    mos_code: str
    title: str
    branch: str
    cmf: str  # Career Management Field
    is_combat_arms: bool


@dataclass(frozen=True)
class EquipmentLINDefinition:
    lin: str
    niin: str
    nsn: str
    nomenclature: str
    equipment_category: str  # TRACKED_COMBAT, WHEELED_TACTICAL, ARTILLERY, COMMS
    erc: str  # Equipment Readiness Code: P (Pacing), A (Principal), B/C (Secondary)
    unit_replacement_cost: float
    mean_hours_between_faults: float
    maintenance_mos: str


@dataclass(frozen=True)
class RepairPartCatalogItem:
    niin: str
    nsn: str
    nomenclature: str
    applies_to_lin: str
    supply_class: str  # IX (Repair Parts)
    unit_of_issue: str
    unit_price: float
    is_critical_nmc_driver: bool


# 1. Force Structure Hierarchy (FMSWeb Reference)
ARMY_UNITS: List[UnitDefinition] = [
    UnitDefinition(
        uic="WAAA01",
        parent_uic=None,
        unit_name="III Armored Corps HQ",
        echelon="CORPS",
        unit_type="CORPS_HQ",
        home_station="Fort Cavazos, TX",
        dodaac="W80A01",
        fund_center="A2020III",
        auth_personnel=45,
    ),
    UnitDefinition(
        uic="WAAB01",
        parent_uic="WAAA01",
        unit_name="1st Cavalry Division HQ",
        echelon="DIV",
        unit_type="DIV_HQ",
        home_station="Fort Cavazos, TX",
        dodaac="W80B01",
        fund_center="A20201CD",
        auth_personnel=60,
    ),
    UnitDefinition(
        uic="WAAC01",
        parent_uic="WAAB01",
        unit_name="2nd Armored Brigade Combat Team (2ABCT), 1CD",
        echelon="BDE",
        unit_type="ABCT_HQ",
        home_station="Fort Cavazos, TX",
        dodaac="W80C01",
        fund_center="A20202AB",
        auth_personnel=75,
    ),
    UnitDefinition(
        uic="WAA1AA",
        parent_uic="WAAC01",
        unit_name="1st Battalion, 8th Cavalry Regiment (1-8 CAV)",
        echelon="BN",
        unit_type="COMBINED_ARMS_BN",
        home_station="Fort Cavazos, TX",
        dodaac="W811AA",
        fund_center="A202018C",
        auth_personnel=80,
    ),
    UnitDefinition(
        uic="WAA1A0",
        parent_uic="WAA1AA",
        unit_name="Alpha Company, 1-8 CAV (Tank Company)",
        echelon="CO",
        unit_type="ARMOR_CO",
        home_station="Fort Cavazos, TX",
        dodaac="W811A0",
        fund_center="A202018A",
        auth_personnel=62,
    ),
    UnitDefinition(
        uic="WAA1B0",
        parent_uic="WAA1AA",
        unit_name="Bravo Company, 1-8 CAV (Mechanized Infantry)",
        echelon="CO",
        unit_type="MECH_INF_CO",
        home_station="Fort Cavazos, TX",
        dodaac="W811B0",
        fund_center="A202018B",
        auth_personnel=110,
    ),
    UnitDefinition(
        uic="WAA2AA",
        parent_uic="WAAC01",
        unit_name="1st Battalion, 82nd Field Artillery Regiment (1-82 FA)",
        echelon="BN",
        unit_type="FA_BN",
        home_station="Fort Cavazos, TX",
        dodaac="W812AA",
        fund_center="A202082F",
        auth_personnel=95,
    ),
    UnitDefinition(
        uic="WAA3AA",
        parent_uic="WAAC01",
        unit_name="15th Brigade Support Battalion (15th BSB)",
        echelon="BN",
        unit_type="BSB",
        home_station="Fort Cavazos, TX",
        dodaac="W813AA",
        fund_center="A202015B",
        auth_personnel=130,
    ),
]

UNIT_BY_UIC: Dict[str, UnitDefinition] = {u.uic: u for u in ARMY_UNITS}


# 2. Ranks & Pay Grades (IPPS-A Reference)
ARMY_RANKS: List[RankDefinition] = [
    RankDefinition("E-1", "PV1", "Private", "ENLISTED", 0, 0, 2017.20),
    RankDefinition("E-2", "PV2", "Private Second Class", "ENLISTED", 6, 6, 2261.10),
    RankDefinition("E-3", "PFC", "Private First Class", "ENLISTED", 12, 6, 2377.50),
    RankDefinition("E-4", "SPC", "Specialist", "ENLISTED", 24, 12, 2633.70),
    RankDefinition("E-5", "SGT", "Sergeant", "ENLISTED", 36, 12, 3180.00),
    RankDefinition("E-6", "SSG", "Staff Sergeant", "ENLISTED", 72, 24, 3891.60),
    RankDefinition("E-7", "SFC", "Sergeant First Class", "ENLISTED", 120, 36, 4799.10),
    RankDefinition("E-8", "MSG", "Master Sergeant", "ENLISTED", 168, 36, 5637.60),
    RankDefinition("E-9", "SGM", "Sergeant Major", "ENLISTED", 216, 36, 6789.00),
    RankDefinition("W-1", "WO1", "Warrant Officer 1", "WARRANT", 48, 0, 3791.10),
    RankDefinition("W-2", "CW2", "Chief Warrant Officer 2", "WARRANT", 72, 24, 4560.90),
    RankDefinition("W-3", "CW3", "Chief Warrant Officer 3", "WARRANT", 120, 36, 5580.00),
    RankDefinition("O-1", "2LT", "Second Lieutenant", "OFFICER", 0, 0, 3826.20),
    RankDefinition("O-2", "1LT", "First Lieutenant", "OFFICER", 18, 18, 4969.20),
    RankDefinition("O-3", "CPT", "Captain", "OFFICER", 48, 30, 6774.30),
    RankDefinition("O-4", "MAJ", "Major", "OFFICER", 120, 48, 8392.20),
    RankDefinition("O-5", "LTC", "Lieutenant Colonel", "OFFICER", 180, 60, 9986.40),
    RankDefinition("O-6", "COL", "Colonel", "OFFICER", 240, 60, 12210.30),
]

RANK_BY_GRADE: Dict[str, RankDefinition] = {r.pay_grade: r for r in ARMY_RANKS}

NEXT_PROMOTION_GRADE: Dict[str, Optional[str]] = {
    "E-1": "E-2",
    "E-2": "E-3",
    "E-3": "E-4",
    "E-4": "E-5",
    "E-5": "E-6",
    "E-6": "E-7",
    "E-7": "E-8",
    "E-8": "E-9",
    "E-9": None,
    "W-1": "W-2",
    "W-2": "W-3",
    "W-3": None,
    "O-1": "O-2",
    "O-2": "O-3",
    "O-3": "O-4",
    "O-4": "O-5",
    "O-5": "O-6",
    "O-6": None,
}


# 3. Military Occupational Specialties (MOS)
ARMY_MOS_LIST: List[MOSDefinition] = [
    MOSDefinition("11B", "Infantryman", "Infantry", "11", True),
    MOSDefinition("19K", "M1 Armor Crewman", "Armor", "19", True),
    MOSDefinition("19D", "Cavalry Scout", "Armor", "19", True),
    MOSDefinition("13B", "Cannon Crewmember", "Field Artillery", "13", True),
    MOSDefinition("91A", "M1 Abrams Tank System Maintainer", "Ordnance", "91", False),
    MOSDefinition("91M", "Bradley Fighting Vehicle System Maintainer", "Ordnance", "91", False),
    MOSDefinition("91B", "Wheeled Vehicle Mechanic", "Ordnance", "91", False),
    MOSDefinition("92A", "Automated Logistical Specialist", "Quartermaster", "92", False),
    MOSDefinition("88M", "Motor Transport Operator", "Transportation", "88", False),
    MOSDefinition("25B", "Information Technology Specialist", "Signal", "25", False),
    MOSDefinition("35F", "Intelligence Analyst", "Military Intelligence", "35", False),
    MOSDefinition("42A", "Human Resources Specialist", "Adjutant General", "42", False),
]

MOS_BY_CODE: Dict[str, MOSDefinition] = {m.mos_code: m for m in ARMY_MOS_LIST}


# 4. Equipment End-Items (FMSWeb MTOE / GCSS-Army Material Master)
ARMY_EQUIPMENT_LINS: List[EquipmentLINDefinition] = [
    EquipmentLINDefinition(
        lin="T13168",
        niin="016884512",
        nsn="2350-01-688-4512",
        nomenclature="TANK, COMBAT, FULL TRACKED: 120MM GUN M1A2 SEPv3",
        equipment_category="TRACKED_COMBAT",
        erc="P",
        unit_replacement_cost=8950000.0,
        mean_hours_between_faults=65.0,
        maintenance_mos="91A",
    ),
    EquipmentLINDefinition(
        lin="F60564",
        niin="016742290",
        nsn="2350-01-674-2290",
        nomenclature="FIGHTING VEHICLE, FULL TRACKED: INFANTRY M2A4 BRADLEY",
        equipment_category="TRACKED_COMBAT",
        erc="P",
        unit_replacement_cost=4350000.0,
        mean_hours_between_faults=80.0,
        maintenance_mos="91M",
    ),
    EquipmentLINDefinition(
        lin="H57642",
        niin="016198331",
        nsn="2350-01-619-8331",
        nomenclature="HOWITZER, MEDIUM, SELF-PROPELLED: 155MM M109A7 PALADIN",
        equipment_category="ARTILLERY",
        erc="P",
        unit_replacement_cost=6100000.0,
        mean_hours_between_faults=75.0,
        maintenance_mos="91B",
    ),
    EquipmentLINDefinition(
        lin="J05001",
        niin="016551109",
        nsn="2320-01-655-1109",
        nomenclature="TRUCK, UTILITY: JLTV M1280 GENERAL PURPOSE",
        equipment_category="WHEELED_TACTICAL",
        erc="A",
        unit_replacement_cost=415000.0,
        mean_hours_between_faults=140.0,
        maintenance_mos="91B",
    ),
    EquipmentLINDefinition(
        lin="T61908",
        niin="015472011",
        nsn="2320-01-547-2011",
        nomenclature="TRUCK, CARGO: 5-TON MTV M1083A1P2",
        equipment_category="WHEELED_TACTICAL",
        erc="A",
        unit_replacement_cost=285000.0,
        mean_hours_between_faults=160.0,
        maintenance_mos="91B",
    ),
    EquipmentLINDefinition(
        lin="R45543",
        niin="015923841",
        nsn="5820-01-592-3841",
        nomenclature="RADIO SET: AN/PRC-158 MULTI-CHANNEL MANPACK",
        equipment_category="COMMS",
        erc="B",
        unit_replacement_cost=42000.0,
        mean_hours_between_faults=250.0,
        maintenance_mos="25B",
    ),
]

LIN_BY_CODE: Dict[str, EquipmentLINDefinition] = {e.lin: e for e in ARMY_EQUIPMENT_LINS}


# 5. Class IX Repair Parts Catalog (GCSS-Army Supply / DLA Integration)
REPAIR_PARTS_CATALOG: List[RepairPartCatalogItem] = [
    RepairPartCatalogItem(
        niin="014391882",
        nsn="2835-01-439-1882",
        nomenclature="ENGINE, GAS TURBINE: AGT1500 POWERPACK ASSEMBLY",
        applies_to_lin="T13168",
        supply_class="IX",
        unit_of_issue="EA",
        unit_price=985000.00,
        is_critical_nmc_driver=True,
    ),
    RepairPartCatalogItem(
        niin="015112098",
        nsn="2530-01-511-2098",
        nomenclature="TRACK SHOE ASSEMBLY, T158LL HEAVY DUTY",
        applies_to_lin="T13168",
        supply_class="IX",
        unit_of_issue="AY",
        unit_price=3850.00,
        is_critical_nmc_driver=False,
    ),
    RepairPartCatalogItem(
        niin="016024410",
        nsn="1240-01-602-4410",
        nomenclature="SIGHT, THERMAL IMAGING: COMMANDER INDEPENDENT THERMAL VIEWER",
        applies_to_lin="T13168",
        supply_class="IX",
        unit_of_issue="EA",
        unit_price=142000.00,
        is_critical_nmc_driver=True,
    ),
    RepairPartCatalogItem(
        niin="015889312",
        nsn="2520-01-588-9312",
        nomenclature="TRANSMISSION, CROSS-DRIVE HMPT-800-3ECB",
        applies_to_lin="F60564",
        supply_class="IX",
        unit_of_issue="EA",
        unit_price=215000.00,
        is_critical_nmc_driver=True,
    ),
    RepairPartCatalogItem(
        niin="014987221",
        nsn="4320-01-498-7221",
        nomenclature="PUMP, HYDRAULIC RAM: TURRET TRAVERSE & ELEVATION",
        applies_to_lin="H57642",
        supply_class="IX",
        unit_of_issue="EA",
        unit_price=28400.00,
        is_critical_nmc_driver=True,
    ),
    RepairPartCatalogItem(
        niin="016334901",
        nsn="2920-01-633-4901",
        nomenclature="ALTERNATOR, 400 AMP TACTICAL VEHICLE",
        applies_to_lin="J05001",
        supply_class="IX",
        unit_of_issue="EA",
        unit_price=4120.00,
        is_critical_nmc_driver=False,
    ),
    RepairPartCatalogItem(
        niin="015192837",
        nsn="2530-01-519-2837",
        nomenclature="HUB ASSEMBLY, CENTRAL TIRE INFLATION SYSTEM (CTIS)",
        applies_to_lin="T61908",
        supply_class="IX",
        unit_of_issue="EA",
        unit_price=2750.00,
        is_critical_nmc_driver=False,
    ),
    RepairPartCatalogItem(
        niin="016109944",
        nsn="5998-01-610-9944",
        nomenclature="CIRCUIT CARD ASSEMBLY: CRYPTOGRAPHIC TRANSCEIVER MODULE",
        applies_to_lin="R45543",
        supply_class="IX",
        unit_of_issue="EA",
        unit_price=6900.00,
        is_critical_nmc_driver=True,
    ),
]

PARTS_BY_LIN: Dict[str, List[RepairPartCatalogItem]] = {}
for _part in REPAIR_PARTS_CATALOG:
    PARTS_BY_LIN.setdefault(_part.applies_to_lin, []).append(_part)


# Unit MTOE Equipment Authorizations (FMSWeb Unit -> LIN -> Authorized Qty)
UNIT_MTOE_EQUIPMENT_AUTH: Dict[str, Dict[str, int]] = {
    "WAAA01": {"J05001": 6, "R45543": 12},
    "WAAB01": {"J05001": 8, "R45543": 16},
    "WAAC01": {"J05001": 10, "T61908": 6, "R45543": 20},
    "WAA1AA": {"T13168": 2, "F60564": 2, "J05001": 12, "T61908": 8, "R45543": 18},
    "WAA1A0": {"T13168": 14, "J05001": 4, "T61908": 2, "R45543": 16},
    "WAA1B0": {"F60564": 14, "J05001": 4, "T61908": 3, "R45543": 18},
    "WAA2AA": {"H57642": 18, "J05001": 8, "T61908": 12, "R45543": 20},
    "WAA3AA": {"J05001": 14, "T61908": 24, "R45543": 16},
}

SURNAMES = [
    "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
    "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis",
    "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres",
    "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera",
    "Campbell", "Mitchell", "Carter", "Roberts", "Kowalski", "Vance", "Mercer", "Reeves",
]

FIRST_NAMES = [
    "James", "Michael", "Robert", "John", "David", "William", "Richard", "Joseph",
    "Thomas", "Christopher", "Charles", "Daniel", "Matthew", "Anthony", "Mark",
    "Marcus", "Elena", "Sarah", "Jessica", "Ashley", "Amanda", "Samantha", "Rachel",
    "Carlos", "Miguel", "Alejandro", "Devon", "Brandon", "Tyler", "Zachary", "Hannah",
    "Victoria", "Natalie", "Lauren", "Kayla", "Brianna", "Jordan", "Cameron", "Logan",
]
