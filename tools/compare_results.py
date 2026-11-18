"""Compare HermiT and Nemo exports and check the 14 competency questions."""

import argparse
import csv
from pathlib import Path


COMMON_RELATIONS = (
    "menuDish", "containsIngredient", "violation", "complies", "safeFor",
    "unsafeFor", "unknownFor", "spicyBecause", "dairyFree", "halalWithFixtureException",
)
# Compared only when the OWL export contains them: verify_owl_owlready.py writes these files,
# VerifyOntology.java does not yet.
TAXONOMY_RELATIONS = (
    "compositeIngredient", "plantBasedDish", "seafoodDish", "pizzaIngredient",
    "multiRestrictionCustomer", "safeForEveryRestriction", "lightDish",
)


def load(directory, relation):
    with (directory / f"{relation}.csv").open(encoding="utf-8", newline="") as source:
        return set(map(tuple, csv.reader(source)))


def require(condition, question):
    if not condition:
        raise SystemExit(f"Competency check failed: {question}")


def compare(owl_dir, nemo_dir):
    results = {}
    for relation in COMMON_RELATIONS:
        owl = load(owl_dir, relation)
        nemo = load(nemo_dir, relation)
        if owl != nemo:
            raise SystemExit(f"{relation}: HermiT only {sorted(owl - nemo)}, Nemo only {sorted(nemo - owl)}")
        results[relation] = owl
    taxonomy = {}
    for relation in TAXONOMY_RELATIONS:
        if (owl_dir / f"{relation}.csv").exists():
            owl = load(owl_dir, relation)
            nemo = load(nemo_dir, relation)
            if owl != nemo:
                raise SystemExit(f"{relation}: HermiT only {sorted(owl - nemo)}, Nemo only {sorted(nemo - owl)}")
            taxonomy[relation] = owl

    menu = {dish for dish, in results["menuDish"]}
    contains = results["containsIngredient"]
    violates = results["violation"]
    complies = results["complies"]
    safe = results["safeFor"]
    unsafe = results["unsafeFor"]
    unknown = results["unknownFor"]
    require(len(menu) == 16 and sum(dish.endswith("Pizza") for dish in menu) == 4, "menu scope")

    vegan = {"CashewVegetableStirFry", "ChickpeaTomatoStew", "TofuRiceBowl", "VeganGardenPizza"}
    require({dish for dish, customer in safe if customer == "anna" and dish in menu} == vegan, "Q1")
    require({dish for dish, policy in complies if policy == "NutAllergy" and dish in menu}
            == menu - {"PestoSpecialePizza", "CashewVegetableStirFry"}, "Q2")
    require(("MargheritaPizza", "VegetarianDiet") in complies, "Q3")
    require({dish for dish, ingredient in contains if ingredient == "Milk"}
            == {"MargheritaPizza", "PestoSpecialePizza", "CreamyMushroomPasta",
                "CaesarSalad", "Cheeseburger"}, "Q4")
    require({dish for dish, customer in safe if customer == "omar" and dish in menu}
            == menu - {"PestoSpecialePizza", "CashewVegetableStirFry", "PorkShoyuRamen"}
            and ("PorkShoyuRamen", "HalalDiet", "Pork") in violates, "Q5")
    require(results["spicyBecause"] == {("ThaiGreenCurry", "ChiliFlakes")}, "Q6")
    pesto = {
        "AnimalRennet", "Basil", "Gluten", "Lactose", "MicrobialRennet", "Milk", "Mozzarella", "NormalDough",
        "OliveOil", "Parmesan", "Pesto", "PineNut", "Rucola", "Water", "WheatFlour", "Yeast",
    }
    require({ingredient for dish, ingredient in contains if dish == "PestoSpecialePizza"} == pesto, "Q7")
    require(("PestoSpecialePizza", "NutAllergy") not in complies
            and ("PestoSpecialePizza", "NutAllergy", "PineNut") in violates, "Q8")
    require(("VeganGardenPizza",) in results["dairyFree"]
            and ("VeganGardenPizza", "mia") in safe, "Q9")
    require(load(owl_dir, "unsatisfiable") == {("VegetarianSalamiDish",)}
            and load(nemo_dir, "integrityViolation") == {("VegetarianSalamiDish", "Salami")}, "Q10")
    gluten_cases = {"MargheritaPizza", "PestoSpecialePizza", "TonnoPizza", "PorkShoyuRamen"}
    require(all((dish, "GlutenIntolerance", "Gluten") in violates for dish in gluten_cases)
            and all((dish, "GlutenIntolerance") not in complies for dish in gluten_cases), "Q11")
    unknown_dressing = ("UnknownDressingBowl", "lisa")
    require(unknown_dressing in unknown and unknown_dressing not in safe
            and unknown_dressing in load(nemo_dir, "noKnownBlockerFor")
            and ("TofuRiceBowl", "lisa") in safe, "Q12")
    require(results["halalWithFixtureException"] == {("CertifiedGelatinFixture",)}
            and all((dish, "omar") in unsafe
                    for dish in ("CertifiedGelatinFixture", "GelatinAndPorkFixture")), "Q13")
    require({("TonnoPizza", "VegetarianDiet", "Tuna"),
             ("ThaiGreenCurry", "VegetarianDiet", "Anchovy")} <= violates, "Q14")
    print(f"Passed all 14 competency checks. Both engines agree on "
          f"{sum(map(len, results.values()))} tuples across {len(results)} relations.")
    if taxonomy:
        print(f"They also agree on {sum(map(len, taxonomy.values()))} tuples across "
              f"{len(taxonomy)} taxonomy relations.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owl_results", type=Path)
    parser.add_argument("nemo_results", type=Path)
    args = parser.parse_args()
    compare(args.owl_results, args.nemo_results)
