"""Export HermiT results with owlready2, as an alternative to verify_owl.py when Protégé is not installed.

It writes the same relation files as VerifyOntology.java, plus one file for each class that
uses the ingredient taxonomy or the constructs beyond ALC. It needs `pip install owlready2` and a Java runtime.
It does not run the OWL 2 DL profile check: only verify_owl.py does that.
"""

import argparse
from pathlib import Path

from owlready2 import Nothing, default_world, get_ontology, sync_reasoner


ROOT = Path(__file__).resolve().parents[1]
COMPLIANCE_CLASSES = {
    "VeganDiet": "VeganDish",
    "VegetarianDiet": "VegetarianDish",
    "PescatarianDiet": "PescatarianDish",
    "HalalDiet": "HalalCompatibleDish",
    "KosherDiet": "KosherCompatibleDish",
    "NutAllergy": "NutFreeDish",
    "GlutenIntolerance": "GlutenFreeDish",
    "LactoseIntolerance": "LactoseFreeDish",
    "PeanutAllergy": "PeanutFreeDish",
    "SoyAllergy": "SoyFreeDish",
    "EggAllergy": "EggFreeDish",
    "ShellfishAllergy": "ShellfishFreeDish",
    "FishAllergy": "FishFreeDish",
}
TAXONOMY_CLASSES = {
    "CompositeIngredient": "compositeIngredient",
    "PlantBasedDish": "plantBasedDish",
    "SeafoodDish": "seafoodDish",
    "PizzaIngredient": "pizzaIngredient",
    "MultiRestrictionCustomer": "multiRestrictionCustomer",
    "SafeForEveryRestrictionDish": "safeForEveryRestriction",
    "LightDish": "lightDish",
}


def evaluate(ontology_path, output):
    ontology = get_ontology(ontology_path.resolve().as_uri()).load()
    with ontology:
        sync_reasoner(infer_property_values=True, debug=0)

    def name(entity):
        return str(entity.label.first() or entity.name)

    instances = {name(cls): {item.name for item in cls.instances()} for cls in ontology.classes()}

    def values(*properties):
        result = {}
        for prop in ontology.object_properties():
            if prop.name in properties:
                for subject, value in prop.get_relations():
                    result.setdefault(subject.name, set()).add(value.name)
        return result

    contains = values("contains", "hasIngredient", "hasBase")
    violations = values("violatesRestriction")
    categories = values("ingredientCategory")
    spiciness = values("hasSpiciness")
    forbids = values("forbids")
    restrictions = values("hasRestriction")

    unsatisfiable = {name(cls) for cls in default_world.inconsistent_classes() if cls is not Nothing}
    if unsatisfiable != {"VegetarianSalamiDish"}:
        raise SystemExit(f"Unexpected unsatisfiable classes: {sorted(unsatisfiable)}")

    facts = {"unsatisfiable": {("VegetarianSalamiDish",)}}

    def add(relation, *columns):
        facts.setdefault(relation, set()).add(columns)

    for restriction, class_name in COMPLIANCE_CLASSES.items():
        for dish in instances[class_name]:
            add("complies", dish, restriction)
    for relation, class_name in (("menuDish", "MenuDish"), ("dairyFree", "DairyFreeDish"),
                                 ("halalWithFixtureException", "HalalWithFixtureException")):
        for dish in instances[class_name]:
            add(relation, dish)
    for class_name, relation in TAXONOMY_CLASSES.items():
        facts.setdefault(relation, set())
        for item in instances[class_name]:
            add(relation, item)

    for dish in instances["Dish"]:
        dish_violations = violations.get(dish, set())
        for ingredient in contains.get(dish, set()):
            add("containsIngredient", dish, ingredient)
            if dish in instances["SpicyDish"] and "HotSpicinessLevel" in spiciness.get(ingredient, set()):
                add("spicyBecause", dish, ingredient)
            for restriction in dish_violations:
                if forbids.get(restriction, set()) & categories.get(ingredient, set()):
                    add("violation", dish, restriction, ingredient)
        for customer in instances["Customer"]:
            held = restrictions.get(customer, set())
            decision = "unknownFor"
            if held & dish_violations:
                decision = "unsafeFor"
            elif dish in instances["CompleteRecipe"] and all(
                    dish in instances[COMPLIANCE_CLASSES[restriction]] for restriction in held):
                decision = "safeFor"
            add(decision, dish, customer)

    output.mkdir(parents=True, exist_ok=True)
    for relation, rows in facts.items():
        lines = "".join(",".join(row) + "\n" for row in sorted(rows))
        (output / f"{relation}.csv").write_text(lines, encoding="utf-8")
    fixtures = len(instances["Dish"]) - len(instances["MenuDish"])
    print(f"Consistent. {len(instances['MenuDish'])} menu dishes, {fixtures} evaluation dishes, "
          f"{len(instances['Customer'])} customers, {len(instances)} named classes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Directory for the exported relation files")
    parser.add_argument("--ontology", type=Path, default=ROOT / "code.rdf")
    args = parser.parse_args()
    evaluate(args.ontology, args.output)
