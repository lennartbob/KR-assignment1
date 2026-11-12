"""Build code.rdf from the WebProtégé taxonomy and the shared restaurant CSVs."""

import argparse
import csv
import os
from collections import defaultdict
from functools import cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_IRI = "urn:webprotege:ontology:24f24fb3-ac8e-4130-8e1c-8d5a4614a18e"
NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "ss": ONTOLOGY_IRI + "#",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
LEGACY_CLASSES = {
    "Pizzas": "Pizza",
    "Ingrediënts": "Ingredient",
    "Customers": "Customer",
    "Diets": "Diet",
    "Dough_Types": "DoughBase",
    "Spicyness": "SpicinessLevel",
    "Nut_Allergy_Diet": "NutAllergy",
    "Lactose_Intolerant_Diet": "LactoseIntolerance",
    "Vegan_Diet": "VeganDiet",
    "Vegetarian_Diet": "VegetarianDiet",
    "Pescatarian_Diet": "PescatarianDiet",
    "Halal_Diet": "HalalDiet",
    "Kosher_Diet": "KosherDiet",
    "Margherita_Pizza": "MargheritaPizzaType",
    "Pesto_Speciale_Pizza": "PestoSpecialePizzaType",
    "Vegan_Garden_Pizza": "VeganGardenPizzaType",
    "Tonno_Pizza": "TonnoPizzaType",
    "Tomota_Sauce": "TomatoSauceType",
}
LEGACY_INGREDIENT_TYPES = {
    "Anchovy_Fish": "Anchovy", "Basil_Herb": "Basil", "Bell_Pepper_Pepper": "BellPepper",
    "Egg_Base": "Egg", "Mozzarella_Cheese": "Mozzarella", "Mushroom_Fungus": "Mushroom",
    "Normal_Dough_Type": "NormalDough", "Olive_Oil_Base": "OliveOil", "Onion_Vegetable": "Onion",
    "Oregano_Herb": "Oregano", "Parmesan_Cheese": "Parmesan", "Pesto_Sauce": "Pesto",
    "Pine_Nut_Nut": "PineNut", "Salt_Base": "Salt", "Tomato_Vegetable": "Tomato",
    "Tuna_Fish": "Tuna", "Vegan_Cheese_Cheese": "VeganCheese", "Vegan_Dough_Type": "VeganDough",
    "Water_Base": "Water", "Wheat_Flour_Base": "WheatFlour", "Yeast_Base": "Yeast",
}
RETIRED_PIZZA_TYPES = {
    "Hawaiian_Pizza", "Pepperoni_Pizza", "Quattro_Formaggi_Pizza", "Vegetariana_Pizza",
}
RESTRICTION_CLASSES = {
    "VeganDiet": "VeganDish",
    "VegetarianDiet": "VegetarianDish",
    "PescatarianDiet": "PescatarianDish",
    "HalalDiet": "HalalCompatibleDish",
    "KosherDiet": "KosherCompatibleDish",
    "NutAllergy": "NutFreeDish",
    "GlutenIntolerance": "GlutenFreeDish",
    "LactoseIntolerance": "LactoseFreeDish",
}
DISH_TYPES = {
    "PorkShoyuRamen": "Ramen",
    "ThaiGreenCurry": "Curry",
    "BeefBurger": "Burger",
    "CreamyMushroomPasta": "Pasta",
    "TofuRiceBowl": "RiceBowl",
    "UnknownDressingBowl": "RiceBowl",
    "CashewVegetableStirFry": "StirFry",
    "ChickpeaTomatoStew": "Stew",
}
RECIPE_TAGS = {"CompleteRecipe", "EvaluationFixture"}
INGREDIENT_METADATA = {"UnknownComposition", "HalalCertified"}


def qname(name):
    prefix, local = name.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


ABOUT = qname("rdf:about")
RESOURCE = qname("rdf:resource")
PARSE_TYPE = qname("rdf:parseType")


def iri(identifier):
    return NS["ss"] + identifier


def element(tag, parent=None, *, about=None, resource=None, collection=False):
    node = ET.Element(qname(tag))
    if about is not None:
        node.set(ABOUT, about)
    if resource is not None:
        node.set(RESOURCE, resource)
    if collection:
        node.set(PARSE_TYPE, "Collection")
    if parent is not None:
        parent.append(node)
    return node


def label(node, value):
    element("rdfs:label", node).set(XML_LANG, "en")
    node[-1].text = value


def reference(resource):
    return element("rdf:Description", about=resource)


def restriction(prop, operator, value):
    node = element("owl:Restriction")
    element("owl:onProperty", node, resource=iri(prop))
    if isinstance(value, str):
        element(operator, node, resource=value)
    else:
        element(operator, node).append(value)
    return node


def expression(operator, *members):
    if len(members) == 1:
        return members[0]
    node = element("owl:Class")
    element(operator, node, collection=True).extend(members)
    return node


def complement(member):
    node = element("owl:Class")
    element("owl:complementOf", node).append(member)
    return node


def only_known(prop, values):
    if not values:
        return restriction(prop, "owl:allValuesFrom", NS["owl"] + "Nothing")
    node = element("owl:Class")
    element("owl:oneOf", node, collection=True).extend(reference(value) for value in sorted(values))
    return restriction(prop, "owl:allValuesFrom", node)


def read_pairs(filename, headers):
    with (ROOT / "data" / filename).open(encoding="utf-8", newline="") as source:
        reader = csv.reader(source)
        if next(reader, None) != list(headers):
            raise ValueError(f"{filename}: expected columns {', '.join(headers)}")
        rows = set()
        for number, row in enumerate(reader, 2):
            if len(row) != 2 or any(not value.isascii() or not value.isalnum() for value in row):
                raise ValueError(f"{filename}:{number}: expected two ASCII identifiers")
            pair = tuple(row)
            if pair in rows:
                raise ValueError(f"{filename}:{number}: duplicate {pair}")
            rows.add(pair)
        return sorted(rows)


def grouped(rows):
    result = defaultdict(set)
    for key, value in rows:
        result[key].add(value)
    return result


def add_class(tree, name, parent=None, definition=None):
    node = element("owl:Class", tree, about=iri(name))
    label(node, name)
    if parent:
        element("rdfs:subClassOf", node, resource=parent)
    if definition is not None:
        element("owl:equivalentClass", node).append(definition)
    return node


def add_property(tree, name, domain, range_, parent=None, transitive=False):
    prop = element("owl:ObjectProperty", tree, about=iri(name))
    element("rdfs:domain", prop, resource=domain)
    element("rdfs:range", prop, resource=range_)
    if parent:
        element("rdfs:subPropertyOf", prop, resource=iri(parent))
    if transitive:
        element("rdf:type", prop, resource=NS["owl"] + "TransitiveProperty")
    return prop


def add_individual(tree, name, class_iri, display=None):
    node = element("owl:NamedIndividual", tree, about=iri(name))
    element("rdf:type", node, resource=class_iri)
    if display:
        label(node, display)
    return node


def add_type(individual, class_expression):
    element("rdf:type", individual).append(class_expression)


def add_fact(individual, prop, value):
    element(f"ss:{prop}", individual, resource=iri(value))


def add_distinct(tree, names):
    axiom = element("owl:AllDifferent", tree)
    element("owl:distinctMembers", axiom, collection=True).extend(
        reference(iri(name)) for name in sorted(names)
    )


def build():
    direct = grouped(read_pairs("dish_ingredients.csv", ("dish", "ingredient")))
    bases = grouped(read_pairs("bases.csv", ("dish", "base")))
    parts = grouped(read_pairs("madefrom.csv", ("ingredient", "made_from")))
    tags = grouped(read_pairs("categories.csv", ("item", "category")))
    forbidden = grouped(read_pairs("restrictions.csv", ("restriction", "forbids")))
    customers = grouped(read_pairs("customers.csv", ("customer", "restriction")))
    dishes = set(direct) | set(bases)
    if any(values & bases[dish] for dish, values in direct.items()):
        raise ValueError("A base must occur once across both recipe tables")
    if set(forbidden) != RESTRICTION_CLASSES.keys():
        raise ValueError("The restriction IDs must match the named OWL compliance queries")
    if any((values - {"None"} - forbidden.keys()) or ("None" in values and len(values) > 1)
           for values in customers.values()):
        raise ValueError("Each customer must have known restrictions or the sole value None")

    categories = set().union(*forbidden.values()) | {"HotSpicy", "Dairy"}
    ingredients = set(parts).union(*parts.values(), *direct.values(), *bases.values())
    for item, values in tags.items():
        allowed = RECIPE_TAGS if item in dishes else categories | INGREDIENT_METADATA
        if (item not in dishes and item not in ingredients and item != "Salami") or values - allowed:
            raise ValueError(f"Invalid category rows for {item}: {sorted(values)}")
    ingredients.add("Salami")

    visiting = set()

    @cache
    def components(ingredient):
        if ingredient in visiting:
            raise ValueError(f"Cyclic composition at {ingredient}")
        visiting.add(ingredient)
        result = set(parts[ingredient])
        for component in parts[ingredient]:
            result.update(components(component))
        visiting.remove(ingredient)
        return result

    for ingredient in ingredients:
        components(ingredient)

    tree = ET.parse(ROOT / "ontology" / "webprotege-revision-229.rdf").getroot()
    classes = {}
    legacy_labels = {
        **LEGACY_CLASSES,
        **{label: ingredient + "Type" for label, ingredient in LEGACY_INGREDIENT_TYPES.items()},
        "Hot_Spicyness": "HotSpiciness",
    }
    for node in list(tree.findall(qname("owl:Class"))):
        old_label = node.find(qname("rdfs:label"))
        if old_label is None:
            continue
        if old_label.text in RETIRED_PIZZA_TYPES:
            tree.remove(node)
            continue
        name = legacy_labels.get(old_label.text)
        if name:
            classes[name] = node
            old_label.text = name

    for name, parent in {
        "Dish": None,
        "DietaryRestriction": None,
        "Allergy": "DietaryRestriction",
        "Intolerance": "DietaryRestriction",
        "Certification": None,
        "IngredientCategory": None,
        "CompleteRecipe": "Dish",
        "EvaluationFixture": "Dish",
        "MenuDish": "Dish",
        "GlutenIntolerance": "Intolerance",
        **{name: "Dish" for name in sorted(set(DISH_TYPES.values()))},
    }.items():
        classes[name] = add_class(tree, name, iri(parent) if parent else None)

    for child, parent in {
        "Pizza": "Dish",
        "Diet": "DietaryRestriction",
        "DoughBase": "Ingredient",
        "MushroomType": "Ingredient",
        "VeganCheeseType": "Ingredient",
        "NutAllergy": "Allergy",
        "LactoseIntolerance": "Intolerance",
    }.items():
        node = classes[child]
        for link in node.findall(qname("rdfs:subClassOf")):
            node.remove(link)
        element("rdfs:subClassOf", node, resource=classes[parent].get(ABOUT))

    ingredient_iri = classes["Ingredient"].get(ABOUT)
    add_property(tree, "hasIngredient", iri("Dish"), ingredient_iri, "contains")
    add_property(tree, "hasBase", iri("Dish"), ingredient_iri, "hasIngredient")
    add_property(tree, "madeFrom", ingredient_iri, ingredient_iri, "hasComponent")
    add_property(tree, "hasComponent", ingredient_iri, ingredient_iri, transitive=True)
    contains = add_property(tree, "contains", iri("Dish"), ingredient_iri)
    element("owl:propertyChainAxiom", contains, collection=True).extend(
        [reference(iri("contains")), reference(iri("madeFrom"))]
    )
    add_property(tree, "ingredientCategory", ingredient_iri, iri("IngredientCategory"))
    add_property(tree, "forbids", iri("DietaryRestriction"), iri("IngredientCategory"))
    add_property(tree, "hasRestriction", classes["Customer"].get(ABOUT), iri("DietaryRestriction"))
    add_property(tree, "violatesRestriction", iri("Dish"), iri("DietaryRestriction"))
    add_property(tree, "hasCertification", ingredient_iri, iri("Certification"))
    add_property(tree, "hasSpiciness", ingredient_iri, classes["SpicinessLevel"].get(ABOUT))

    for category in sorted(categories):
        add_individual(tree, f"category_{category}", iri("IngredientCategory"), category)
    add_distinct(tree, (f"category_{category}" for category in categories))
    add_individual(tree, "HalalCertified", iri("Certification"))
    add_individual(tree, "HotSpicinessLevel", classes["HotSpiciness"].get(ABOUT))

    def has_category(category):
        return restriction("ingredientCategory", "owl:hasValue", iri(f"category_{category}"))

    for name in sorted(ingredients):
        legacy_type = classes.get(name + "Type")
        node = add_individual(tree, name, legacy_type.get(ABOUT) if legacy_type is not None else ingredient_iri)
        for component in sorted(parts[name]):
            add_fact(node, "madeFrom", component)
        ingredient_categories = sorted(tags[name] & categories)
        for category in ingredient_categories:
            add_fact(node, "ingredientCategory", f"category_{category}")
        if "UnknownComposition" not in tags[name]:
            add_type(node, only_known("ingredientCategory",
                                      [iri(f"category_{tag}") for tag in ingredient_categories]))
        if "HalalCertified" in tags[name]:
            add_fact(node, "hasCertification", "HalalCertified")
        if "HotSpicy" in tags[name]:
            add_fact(node, "hasSpiciness", "HotSpicinessLevel")
    add_distinct(tree, ingredients)

    for name in sorted(dishes):
        dish_type = classes.get(name + "Type")
        dish_iri = dish_type.get(ABOUT) if dish_type is not None else iri(DISH_TYPES.get(name, "Dish"))
        node = add_individual(tree, name, dish_iri)
        for tag in sorted(tags[name] & RECIPE_TAGS):
            element("rdf:type", node, resource=iri(tag))
        if "EvaluationFixture" not in tags[name]:
            element("rdf:type", node, resource=iri("MenuDish"))
        for ingredient in sorted(direct[name]):
            add_fact(node, "hasIngredient", ingredient)
        for base in sorted(bases[name]):
            add_fact(node, "hasBase", base)
        if "CompleteRecipe" in tags[name]:
            entries = direct[name] | bases[name]
            known = entries.union(*(components(ingredient) for ingredient in entries))
            if any("UnknownComposition" in tags[ingredient] for ingredient in known):
                raise ValueError(f"{name} is marked complete but includes an unknown ingredient")
            add_type(node, only_known("hasIngredient", [iri(ingredient) for ingredient in entries]))
            add_type(node, only_known("contains", [iri(ingredient) for ingredient in known]))
    add_distinct(tree, dishes)

    for name, values in sorted(forbidden.items()):
        node = add_individual(tree, name, classes[name].get(ABOUT), f"{name} restriction")
        for tag in sorted(values):
            add_fact(node, "forbids", f"category_{tag}")
        forbidden_ingredient = expression("owl:unionOf", *(has_category(tag) for tag in sorted(values)))
        violation = restriction("contains", "owl:someValuesFrom", forbidden_ingredient)
        subclass = expression("owl:intersectionOf", reference(iri("Dish")), violation)
        element("rdfs:subClassOf", subclass).append(
            restriction("violatesRestriction", "owl:hasValue", iri(name))
        )
        tree.append(subclass)
        compatible = expression("owl:intersectionOf", reference(iri("CompleteRecipe")),
                                complement(restriction("contains", "owl:someValuesFrom",
                                    expression("owl:unionOf", *(has_category(tag) for tag in sorted(values))))))
        add_class(tree, RESTRICTION_CLASSES[name], definition=compatible)
    add_distinct(tree, forbidden)

    for name, values in sorted(customers.items()):
        node = add_individual(tree, name, classes["Customer"].get(ABOUT))
        for value in sorted(values - {"None"}):
            add_fact(node, "hasRestriction", value)
        add_type(node, only_known("hasRestriction", [iri(value) for value in values - {"None"}]))
    add_distinct(tree, customers)

    add_class(tree, "DairyFreeDish", definition=expression(
        "owl:intersectionOf", reference(iri("CompleteRecipe")),
        complement(restriction("contains", "owl:someValuesFrom", has_category("Dairy"))),
    ))
    add_class(tree, "SpicyDish", definition=expression(
        "owl:intersectionOf", reference(iri("Dish")),
        restriction("contains", "owl:someValuesFrom",
                    restriction("hasSpiciness", "owl:hasValue", iri("HotSpicinessLevel"))),
    ))
    add_class(tree, "VegetarianSalamiDish", definition=expression(
        "owl:intersectionOf", reference(iri("VegetarianDish")),
        restriction("hasIngredient", "owl:hasValue", iri("Salami")),
    ))

    # The hypothetical exception applies to a certified direct ingredient.
    fixture_entries = set().union(*(direct[dish] | bases[dish] for dish in dishes
                                    if RECIPE_TAGS <= tags[dish]))
    ingredient_nodes = {node.get(ABOUT): node for node in tree.findall(qname("owl:NamedIndividual"))}
    for ingredient in sorted(fixture_entries):
        node = ingredient_nodes[iri(ingredient)]
        certifications = [iri("HalalCertified")] if "HalalCertified" in tags[ingredient] else []
        add_type(node, only_known("hasCertification", certifications))
        add_type(node, only_known("hasComponent", [iri(part) for part in components(ingredient)]))
    pork_source = expression("owl:unionOf", has_category("Pork"),
                             restriction("hasComponent", "owl:someValuesFrom", has_category("Pork")))
    allowed_source = expression("owl:unionOf",
                                restriction("hasCertification", "owl:hasValue", iri("HalalCertified")),
                                complement(pork_source))
    add_class(tree, "HalalWithFixtureException", definition=expression(
        "owl:intersectionOf", reference(iri("EvaluationFixture")), reference(iri("CompleteRecipe")),
        restriction("hasIngredient", "owl:someValuesFrom",
                    restriction("hasCertification", "owl:hasValue", iri("HalalCertified"))),
        restriction("hasIngredient", "owl:allValuesFrom", allowed_source),
    ))

    for prefix, namespace in NS.items():
        ET.register_namespace(prefix, namespace)
    ET.indent(tree, space="    ")
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True) + b"\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify that code.rdf matches the inputs")
    args = parser.parse_args()
    destination = ROOT / "code.rdf"
    data = build()
    if args.check:
        if not destination.exists() or destination.read_bytes() != data:
            parser.exit(1, "code.rdf differs from the generated ontology\n")
        return
    with NamedTemporaryFile(dir=ROOT, delete=False) as temporary:
        temporary.write(data)
        staged = Path(temporary.name)
    try:
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
