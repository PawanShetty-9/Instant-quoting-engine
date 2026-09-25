"""Material catalogue for CNC contract manufacturing in Germany.

Every value is a *default* that a manufacturer is expected to tune to their own
purchase prices and machine park. The provenance of each number is documented
in ``docs/COST_MODEL.md``; the short version:

* Densities: EN 573-3 / EN 10088-1 / EN 10083 / DIN 17660 / supplier data sheets.
* Prices (EUR/kg, cut-to-size semi-finished goods, small quantities, Sept 2026):
  derived from LME aluminium (Alumeco, 2,861 EUR/t on 2026-09-24), German
  stainless alloy surcharges (Legierungszuschlag 1.4301 = 2,235 EUR/t,
  1.4404 = 4,047 EUR/t, Sept 2026) plus typical distributor base prices and
  cutting premiums.
* Material removal rates are *effective* job-shop roughing rates (including
  air cuts and tool changes), i.e. roughly 25-35 % of the peak MRR published by
  tool makers (Sandvik Coromant Q = ap * ae * vf / 1000; aluminium > 500 cm3/min,
  steel > 100 cm3/min, titanium 16-49 cm3/min peak).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Material:
    key: str
    name_de: str
    name_en: str
    werkstoff_nr: str
    category: str
    density_g_cm3: float
    price_eur_per_kg: float
    # Effective roughing removal rate on a reference 3-axis VMC (SK40, ~15 kW).
    mrr_rough_cm3_min: float
    # Effective finishing rate: part surface finished per minute.
    finish_rate_cm2_min: float
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def public_dict(self) -> dict:
        return {
            "key": self.key,
            "name_de": self.name_de,
            "name_en": self.name_en,
            "werkstoff_nr": self.werkstoff_nr,
            "category": self.category,
            "density_g_cm3": self.density_g_cm3,
        }


MATERIALS: dict[str, Material] = {
    m.key: m
    for m in (
        Material(
            key="AL_6082_T6",
            name_de="Aluminium EN AW-6082 T6 (AlSi1MgMn)",
            name_en="Aluminium EN AW-6082 T6",
            werkstoff_nr="3.2315",
            category="Aluminium",
            density_g_cm3=2.70,
            price_eur_per_kg=7.50,
            mrr_rough_cm3_min=150.0,
            finish_rate_cm2_min=25.0,
            aliases=("6082", "en aw-6082", "almgsi1", "alsi1mgmn", "aluminium", "aluminum"),
        ),
        Material(
            key="AL_6061_T6",
            name_de="Aluminium EN AW-6061 T6 (AlMg1SiCu)",
            name_en="Aluminium EN AW-6061 T6",
            werkstoff_nr="3.3211",
            category="Aluminium",
            density_g_cm3=2.70,
            price_eur_per_kg=8.00,
            mrr_rough_cm3_min=150.0,
            finish_rate_cm2_min=25.0,
            aliases=("6061", "en aw-6061", "6061-t6", "almg1sicu"),
        ),
        Material(
            key="AL_7075_T651",
            name_de="Aluminium EN AW-7075 T651 (AlZn5,5MgCu)",
            name_en="Aluminium EN AW-7075 T651",
            werkstoff_nr="3.4365",
            category="Aluminium",
            density_g_cm3=2.81,
            price_eur_per_kg=16.00,
            mrr_rough_cm3_min=140.0,
            finish_rate_cm2_min=25.0,
            aliases=("7075", "en aw-7075", "alzn5,5mgcu", "alzn5.5mgcu", "ergal"),
        ),
        Material(
            key="STEEL_S235JR",
            name_de="Baustahl S235JR",
            name_en="Structural steel S235JR",
            werkstoff_nr="1.0038",
            category="Stahl / Steel",
            density_g_cm3=7.85,
            price_eur_per_kg=1.80,
            mrr_rough_cm3_min=45.0,
            finish_rate_cm2_min=12.0,
            aliases=("s235", "s235jr", "st37", "st 37", "mild steel", "baustahl"),
        ),
        Material(
            key="STEEL_C45",
            name_de="Vergütungsstahl C45",
            name_en="Carbon steel C45",
            werkstoff_nr="1.0503",
            category="Stahl / Steel",
            density_g_cm3=7.85,
            price_eur_per_kg=2.20,
            mrr_rough_cm3_min=40.0,
            finish_rate_cm2_min=12.0,
            aliases=("c45", "c45e", "1.1191", "ck45", "aisi 1045", "1045"),
        ),
        Material(
            key="STEEL_42CRMO4",
            name_de="Vergütungsstahl 42CrMo4+QT",
            name_en="Alloy steel 42CrMo4+QT",
            werkstoff_nr="1.7225",
            category="Stahl / Steel",
            density_g_cm3=7.85,
            price_eur_per_kg=3.20,
            mrr_rough_cm3_min=30.0,
            finish_rate_cm2_min=10.0,
            aliases=("42crmo4", "aisi 4140", "4140"),
        ),
        Material(
            key="STEEL_11SMNPB30",
            name_de="Automatenstahl 11SMnPb30",
            name_en="Free-cutting steel 11SMnPb30",
            werkstoff_nr="1.0718",
            category="Stahl / Steel",
            density_g_cm3=7.85,
            price_eur_per_kg=2.10,
            mrr_rough_cm3_min=50.0,
            finish_rate_cm2_min=14.0,
            aliases=("11smnpb30", "9smnpb28", "automatenstahl", "free cutting steel", "12l14"),
        ),
        Material(
            key="SS_1.4301",
            name_de="Edelstahl X5CrNi18-10 (V2A)",
            name_en="Stainless steel X5CrNi18-10 (304)",
            werkstoff_nr="1.4301",
            category="Edelstahl / Stainless",
            density_g_cm3=7.90,
            price_eur_per_kg=5.60,
            mrr_rough_cm3_min=22.0,
            finish_rate_cm2_min=8.0,
            aliases=("1.4301", "x5crni18-10", "v2a", "aisi 304", "304", "stainless", "edelstahl"),
        ),
        Material(
            key="SS_1.4305",
            name_de="Edelstahl X8CrNiS18-9 (V2A, Automatengüte)",
            name_en="Stainless steel X8CrNiS18-9 (303)",
            werkstoff_nr="1.4305",
            category="Edelstahl / Stainless",
            density_g_cm3=7.90,
            price_eur_per_kg=5.80,
            mrr_rough_cm3_min=26.0,
            finish_rate_cm2_min=9.0,
            aliases=("1.4305", "x8crnis18-9", "aisi 303", "303"),
        ),
        Material(
            key="SS_1.4404",
            name_de="Edelstahl X2CrNiMo17-12-2 (V4A)",
            name_en="Stainless steel X2CrNiMo17-12-2 (316L)",
            werkstoff_nr="1.4404",
            category="Edelstahl / Stainless",
            density_g_cm3=8.00,
            price_eur_per_kg=7.40,
            mrr_rough_cm3_min=20.0,
            finish_rate_cm2_min=8.0,
            aliases=("1.4404", "x2crnimo17-12-2", "v4a", "aisi 316l", "316l", "316"),
        ),
        Material(
            key="BRASS_CW614N",
            name_de="Messing CuZn39Pb3 (Ms58)",
            name_en="Brass CuZn39Pb3 (CW614N)",
            werkstoff_nr="CW614N",
            category="Buntmetall / Non-ferrous",
            density_g_cm3=8.47,
            price_eur_per_kg=8.50,
            mrr_rough_cm3_min=110.0,
            finish_rate_cm2_min=22.0,
            aliases=("cw614n", "cuzn39pb3", "ms58", "brass", "messing", "2.0401"),
        ),
        Material(
            key="TI_GRADE5",
            name_de="Titan Grade 5 (Ti6Al4V)",
            name_en="Titanium Grade 5 (Ti-6Al-4V)",
            werkstoff_nr="3.7165",
            category="Titan / Titanium",
            density_g_cm3=4.43,
            price_eur_per_kg=45.00,
            mrr_rough_cm3_min=10.0,
            finish_rate_cm2_min=5.0,
            aliases=("ti6al4v", "ti-6al-4v", "grade 5", "titanium", "titan", "3.7165"),
        ),
        Material(
            key="POM_C",
            name_de="Kunststoff POM-C (Polyacetal)",
            name_en="Plastic POM-C (acetal copolymer)",
            werkstoff_nr="POM-C",
            category="Kunststoff / Plastic",
            density_g_cm3=1.41,
            price_eur_per_kg=9.50,
            mrr_rough_cm3_min=180.0,
            finish_rate_cm2_min=25.0,
            aliases=("pom", "pom-c", "delrin", "acetal", "polyacetal"),
        ),
        Material(
            key="PA6",
            name_de="Kunststoff PA 6 (Polyamid)",
            name_en="Plastic PA 6 (nylon)",
            werkstoff_nr="PA6",
            category="Kunststoff / Plastic",
            density_g_cm3=1.14,
            price_eur_per_kg=7.00,
            mrr_rough_cm3_min=160.0,
            finish_rate_cm2_min=25.0,
            aliases=("pa6", "pa 6", "polyamid", "polyamide", "nylon"),
        ),
        Material(
            key="PEEK",
            name_de="Hochleistungskunststoff PEEK",
            name_en="High-performance plastic PEEK",
            werkstoff_nr="PEEK",
            category="Kunststoff / Plastic",
            density_g_cm3=1.31,
            price_eur_per_kg=110.00,
            mrr_rough_cm3_min=90.0,
            finish_rate_cm2_min=18.0,
            aliases=("peek", "polyetheretherketone"),
        ),
    )
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


_LOOKUP: dict[str, str] = {}
for _m in MATERIALS.values():
    for _alias in (_m.key, _m.werkstoff_nr, _m.name_de, _m.name_en, *_m.aliases):
        _LOOKUP.setdefault(_normalise(_alias), _m.key)


def resolve_material(requested: str) -> Material | None:
    """Resolve a catalogue key, Werkstoffnummer, trade name or alias."""
    if not requested:
        return None
    norm = _normalise(requested)
    if norm in _LOOKUP:
        return MATERIALS[_LOOKUP[norm]]
    if requested in MATERIALS:
        return MATERIALS[requested]
    # Tolerate decorated inputs such as "Aluminium 6082 T6" or "1.4301 (V2A)".
    for alias, key in sorted(_LOOKUP.items(), key=lambda kv: -len(kv[0])):
        if len(alias) >= 3 and re.search(rf"(?<![\w.]){re.escape(alias)}(?![\w])", norm):
            return MATERIALS[key]
    return None
