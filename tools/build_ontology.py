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
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XSD_NON_NEGATIVE_INTEGER = NS["xsd"] + "nonNegativeInteger"
XSD_INTEGER = NS["xsd"] + "integer"
# A light dish has at most this many kcal. datalog/safeslice.rls uses the same number.
LIGHT_DISH_MAX_KCAL = 600
# Classes kept from the WebProtégé baseline, with their names in this ontology.
# Every other baseline class (the pizza-era ingredient and pizza classes) is retired:
# the ingredient taxonomy now comes from data/type_hierarchy.csv.
LEGACY_CLASSES = {
    "Pizzas": "Pizza",
    "Ingrediënts": "Ingredient",
    "Customers": "Customer",
    "Diets": "Diet",
    "Spicyness": "SpicinessLevel",
    "Hot_Spicyness": "HotSpiciness",
    "Medium_Spicyness": "MediumSpiciness",
    "Low_Spicyness": "LowSpiciness",
    "None_Spicyness": "NoSpiciness",
    "Nut_Allergy_Diet": "NutAllergy",
    "Lactose_Intolerant_Diet": "LactoseIntolerance",
    "Vegan_Diet": "VeganDiet",
    "Vegetarian_Diet": "VegetarianDiet",
    "Pescatarian_Diet": "PescatarianDiet",
    "Halal_Diet": "HalalDiet",
    "Kosher_Diet": "KosherDiet",
}
SPICINESS_LEVELS = ("NoSpiciness", "LowSpiciness", "MediumSpiciness", "HotSpiciness")
RESTRICTION_CLASSES = {
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


def number_restriction(prop, operator, count, class_iri):
    """A qualified number restriction. The property must be a simple role."""
    node = element("owl:Restriction")
    element("owl:onProperty", node, resource=iri(prop))
    cardinality = element(operator, node)
    cardinality.set(qname("rdf:datatype"), XSD_NON_NEGATIVE_INTEGER)
    cardinality.text = str(count)
    element("owl:onClass", node, resource=class_iri)
    return node


def at_most_value(prop, maximum):
    """Some value of a data property is an integer of at most the given maximum."""
    bound = element("rdf:Description")
    facet = element("xsd:maxInclusive", bound)
    facet.set(qname("rdf:datatype"), XSD_INTEGER)
    facet.text = str(maximum)
    datatype = element("rdfs:Datatype")
    element("owl:onDatatype", datatype, resource=XSD_INTEGER)
    element("owl:withRestrictions", datatype, collection=True).append(bound)
    return restriction(prop, "owl:someValuesFrom", datatype)


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


def add_disjoint(tree, class_iris):
    class_iris = sorted(class_iris)
    if len(class_iris) < 2:
        return
    axiom = element("owl:AllDisjointClasses", tree)
    element("owl:members", axiom, collection=True).extend(reference(value) for value in class_iris)


def add_covering(node, class_iris):
    element("owl:equivalentClass", node).append(
        expression("owl:unionOf", *(reference(value) for value in sorted(class_iris)))
    )


def single_valued(rows, filename):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError(f"{filename}: {key} has more than one value")
        result[key] = value
    return result


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
    if any(len(values) > 1 for values in bases.values()):
        raise ValueError("A dish has at most one base, because hasBase is functional")

    dish_types = single_valued(read_pairs("dish_types.csv", ("dish", "type")), "dish_types.csv")
    kind_parent = single_valued(read_pairs("type_hierarchy.csv", ("type", "parent")), "type_hierarchy.csv")
    kind_of = single_valued(read_pairs("ingredient_types.csv", ("ingredient", "type")), "ingredient_types.csv")
    kind_tags = grouped(read_pairs("type_categories.csv", ("type", "category")))
    calories = single_valued(read_pairs("dish_calories.csv", ("dish", "kcal")), "dish_calories.csv")
    if set(calories) - dishes or not all(value.isdigit() for value in calories.values()):
        raise ValueError("dish_calories.csv must give known dishes a whole number of kcal")
    if any(dish_types.get(dish) == "Pizza" and kind_of.get(base) != "DoughOrBatter"
           for dish, values in bases.items() for base in values):
        raise ValueError("The base of a pizza must be of type DoughOrBatter")
    if any(dish_types.get(dish) == "Pizza" and not bases[dish] for dish in dishes):
        raise ValueError("Every pizza needs a base")
    if set(dish_types) - dishes:
        raise ValueError(f"dish_types.csv names unknown dishes: {sorted(set(dish_types) - dishes)}")
    if any(parent != "Ingredient" and parent not in kind_parent for parent in kind_parent.values()):
        raise ValueError("type_hierarchy.csv: every parent must be Ingredient or another listed type")
    if set(kind_of) != ingredients or set(kind_of.values()) - kind_parent.keys():
        raise ValueError("Every ingredient needs exactly one known type in ingredient_types.csv")
    if set(kind_tags) - kind_parent.keys() or set().union(*kind_tags.values()) - categories:
        raise ValueError("type_categories.csv must link known types to known categories")
    taken = dishes | ingredients | set(forbidden) | set(RESTRICTION_CLASSES.values()) | set(customers)
    if (set(kind_parent) | set(dish_types.values())) & taken:
        raise ValueError("A type name is already used for a dish, ingredient, restriction or customer")

    def lineage(kind):
        """The type itself and all its ancestors below Ingredient."""
        seen = []
        while kind != "Ingredient":
            if kind in seen:
                raise ValueError(f"Cyclic type hierarchy at {kind}")
            seen.append(kind)
            kind = kind_parent[kind]
        return seen

    for kind in kind_parent:
        lineage(kind)
    # Categories an ingredient gets from its type. They are inferred, not asserted.
    inherited = {name: set().union(*(kind_tags.get(kind, set()) for kind in lineage(kind_of[name])))
                 for name in ingredients}
    for name in sorted(ingredients):
        if tags[name] & inherited[name]:
            raise ValueError(f"categories.csv repeats what the type of {name} already implies: "
                             f"{sorted(tags[name] & inherited[name])}")

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
    for node in list(tree.findall(qname("owl:Class"))):
        old_label = node.find(qname("rdfs:label"))
        name = LEGACY_CLASSES.get(old_label.text) if old_label is not None else None
        if name is None:
            tree.remove(node)
            continue
        classes[name] = node
        old_label.text = name
    if set(classes) != set(LEGACY_CLASSES.values()):
        raise ValueError("The WebProtégé baseline no longer contains all expected classes")

    dish_type_names = sorted(set(dish_types.values()) - {"Pizza"})
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
        "PeanutAllergy": "Allergy",
        "SoyAllergy": "Allergy",
        "EggAllergy": "Allergy",
        "ShellfishAllergy": "Allergy",
        "FishAllergy": "Allergy",
        **{name: "Dish" for name in dish_type_names},
    }.items():
        classes[name] = add_class(tree, name, iri(parent) if parent else None)

    for child, parent in {
        "Pizza": "Dish",
        "Diet": "DietaryRestriction",
        "NutAllergy": "Allergy",
        "LactoseIntolerance": "Intolerance",
    }.items():
        node = classes[child]
        for link in node.findall(qname("rdfs:subClassOf")):
            node.remove(link)
        element("rdfs:subClassOf", node, resource=classes[parent].get(ABOUT))

    def class_iri(name):
        return classes[name].get(ABOUT)

    ingredient_iri = class_iri("Ingredient")

    # Ingredient taxonomy from type_hierarchy.csv. Sibling types are pairwise disjoint.
    for kind in sorted(kind_parent, key=lambda value: (len(lineage(value)), value)):
        classes[kind] = add_class(tree, kind, class_iri(kind_parent[kind]))
    for parent in sorted(set(kind_parent.values())):
        add_disjoint(tree, [class_iri(kind) for kind, value in kind_parent.items() if value == parent])

    # Design patterns: disjoint top-level classes, and two covered partitions.
    add_disjoint(tree, [class_iri(name) for name in (
        "Dish", "Ingredient", "Customer", "DietaryRestriction", "IngredientCategory",
        "Certification", "SpicinessLevel")])
    add_disjoint(tree, [class_iri(name) for name in ("Allergy", "Diet", "Intolerance")])
    add_covering(classes["DietaryRestriction"],
                 [class_iri(name) for name in ("Allergy", "Diet", "Intolerance")])
    add_disjoint(tree, [class_iri(name) for name in SPICINESS_LEVELS])
    add_covering(classes["SpicinessLevel"], [class_iri(name) for name in SPICINESS_LEVELS])
    add_disjoint(tree, [class_iri(name) for name in [*dish_type_names, "Pizza"]])
    add_disjoint(tree, [class_iri("MenuDish"), class_iri("EvaluationFixture")])

    add_property(tree, "hasIngredient", iri("Dish"), ingredient_iri, "contains")
    has_base = add_property(tree, "hasBase", iri("Dish"), ingredient_iri, "hasIngredient")
    element("rdf:type", has_base, resource=NS["owl"] + "FunctionalProperty")
    # madeFrom is the direct, simple role, so it may be irreflexive and asymmetric.
    # Its transitive super role hasComponent is not simple and cannot get these axioms.
    made_from = add_property(tree, "madeFrom", ingredient_iri, ingredient_iri, "hasComponent")
    element("rdf:type", made_from, resource=NS["owl"] + "IrreflexiveProperty")
    element("rdf:type", made_from, resource=NS["owl"] + "AsymmetricProperty")
    add_property(tree, "hasComponent", ingredient_iri, ingredient_iri, transitive=True)
    contains = add_property(tree, "contains", iri("Dish"), ingredient_iri)
    element("owl:propertyChainAxiom", contains, collection=True).extend(
        [reference(iri("contains")), reference(iri("madeFrom"))]
    )
    contained_in = add_property(tree, "isContainedIn", ingredient_iri, iri("Dish"))
    element("owl:inverseOf", contained_in, resource=iri("contains"))
    add_property(tree, "ingredientCategory", ingredient_iri, iri("IngredientCategory"))
    add_property(tree, "forbids", iri("DietaryRestriction"), iri("IngredientCategory"))
    add_property(tree, "hasRestriction", class_iri("Customer"), iri("DietaryRestriction"))
    add_property(tree, "violatesRestriction", iri("Dish"), iri("DietaryRestriction"))
    add_property(tree, "hasCertification", ingredient_iri, iri("Certification"))
    add_property(tree, "hasSpiciness", ingredient_iri, class_iri("SpicinessLevel"))
    has_calories = element("owl:DatatypeProperty", tree, about=iri("hasCalories"))
    element("rdfs:domain", has_calories, resource=iri("Dish"))
    element("rdfs:range", has_calories, resource=XSD_INTEGER)
    element("rdf:type", has_calories, resource=NS["owl"] + "FunctionalProperty")
    # Partial definition with an exact number restriction on the simple role hasBase.
    element("rdfs:subClassOf", classes["Pizza"]).append(
        number_restriction("hasBase", "owl:qualifiedCardinality", 1, class_iri("DoughOrBatter")))

    for category in sorted(categories):
        add_individual(tree, f"category_{category}", iri("IngredientCategory"), category)
    add_distinct(tree, (f"category_{category}" for category in categories))
    add_individual(tree, "HalalCertified", iri("Certification"))
    add_individual(tree, "HotSpicinessLevel", class_iri("HotSpiciness"))

    def has_category(category):
        return restriction("ingredientCategory", "owl:hasValue", iri(f"category_{category}"))

    # A category stated for a type holds for every ingredient of that type and its subtypes.
    for kind, values in sorted(kind_tags.items()):
        for category in sorted(values):
            element("rdfs:subClassOf", classes[kind]).append(has_category(category))

    for name in sorted(ingredients):
        node = add_individual(tree, name, class_iri(kind_of[name]))
        for component in sorted(parts[name]):
            add_fact(node, "madeFrom", component)
        for category in sorted(tags[name] & categories):
            add_fact(node, "ingredientCategory", f"category_{category}")
        ingredient_categories = sorted((tags[name] & categories) | inherited[name])
        if "UnknownComposition" not in tags[name]:
            add_type(node, only_known("ingredientCategory",
                                      [iri(f"category_{tag}") for tag in ingredient_categories]))
        if "HalalCertified" in tags[name]:
            add_fact(node, "hasCertification", "HalalCertified")
        if "HotSpicy" in tags[name]:
            add_fact(node, "hasSpiciness", "HotSpicinessLevel")
    add_distinct(tree, ingredients)

    for name in sorted(dishes):
        node = add_individual(tree, name, class_iri(dish_types.get(name, "Dish")))
        for tag in sorted(tags[name] & RECIPE_TAGS):
            element("rdf:type", node, resource=iri(tag))
        if "EvaluationFixture" not in tags[name]:
            element("rdf:type", node, resource=iri("MenuDish"))
        for ingredient in sorted(direct[name]):
            add_fact(node, "hasIngredient", ingredient)
        for base in sorted(bases[name]):
            add_fact(node, "hasBase", base)
        if name in calories:
            value = element("ss:hasCalories", node)
            value.set(qname("rdf:datatype"), XSD_INTEGER)
            value.text = str(int(calories[name]))
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
        if name == "KosherDiet":
            # Kosher also forbids meat and dairy in the same dish (a rule about a combination).
            def meat_and_dairy():
                return expression("owl:intersectionOf",
                                  restriction("contains", "owl:someValuesFrom", has_category("Meat")),
                                  restriction("contains", "owl:someValuesFrom", has_category("Dairy")))
            combination = expression("owl:intersectionOf", reference(iri("Dish")), meat_and_dairy())
            element("rdfs:subClassOf", combination).append(
                restriction("violatesRestriction", "owl:hasValue", iri(name))
            )
            tree.append(combination)
            compatible = expression("owl:intersectionOf", compatible, complement(meat_and_dairy()))
        add_class(tree, RESTRICTION_CLASSES[name], definition=compatible)
    add_distinct(tree, forbidden)

    for name, values in sorted(customers.items()):
        node = add_individual(tree, name, class_iri("Customer"))
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

    # Definitions that use the ingredient taxonomy and the constructs beyond ALC.
    # An ingredient with at least one stated component (existential restriction).
    add_class(tree, "CompositeIngredient", definition=expression(
        "owl:intersectionOf", reference(ingredient_iri),
        restriction("madeFrom", "owl:someValuesFrom", ingredient_iri),
    ))
    # A complete recipe in which nothing is animal sourced (universal restriction with negation).
    # The reasoner needs the closure axiom on contains and the disjoint ingredient types for this.
    # "Only" does not mean "some", so the definition also asks for at least one ingredient.
    add_class(tree, "PlantBasedDish", definition=expression(
        "owl:intersectionOf", reference(iri("CompleteRecipe")),
        restriction("contains", "owl:someValuesFrom", ingredient_iri),
        restriction("contains", "owl:allValuesFrom",
                    complement(reference(class_iri("AnimalSourcedIngredient")))),
    ))
    # A dish with fish or shellfish at any depth of its recipe (union over two types).
    add_class(tree, "SeafoodDish", definition=expression(
        "owl:intersectionOf", reference(iri("Dish")),
        restriction("contains", "owl:someValuesFrom", expression(
            "owl:unionOf", reference(class_iri("FishProduct")), reference(class_iri("ShellfishProduct")))),
    ))
    # Everything that ends up in some pizza (inverse of the chained property contains).
    add_class(tree, "PizzaIngredient", definition=expression(
        "owl:intersectionOf", reference(ingredient_iri),
        restriction("isContainedIn", "owl:someValuesFrom", class_iri("Pizza")),
    ))
    # A customer with two or more different restrictions (qualified number restriction).
    add_class(tree, "MultiRestrictionCustomer", definition=expression(
        "owl:intersectionOf", reference(class_iri("Customer")),
        number_restriction("hasRestriction", "owl:minQualifiedCardinality", 2, iri("DietaryRestriction")),
    ))
    # A menu dish with a stated energy value of at most 600 kcal (concrete domain).
    add_class(tree, "LightDish", definition=expression(
        "owl:intersectionOf", reference(iri("MenuDish")),
        at_most_value("hasCalories", LIGHT_DISH_MAX_KCAL),
    ))
    # A menu dish that complies with every recorded restriction (intersection of defined classes).
    add_class(tree, "SafeForEveryRestrictionDish", definition=expression(
        "owl:intersectionOf", reference(iri("MenuDish")),
        *(reference(iri(name)) for name in sorted(RESTRICTION_CLASSES.values())),
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
