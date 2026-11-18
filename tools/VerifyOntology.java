import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import org.semanticweb.HermiT.ReasonerFactory;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.model.IRI;
import org.semanticweb.owlapi.model.OWLClass;
import org.semanticweb.owlapi.model.OWLDataFactory;
import org.semanticweb.owlapi.model.OWLNamedIndividual;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyManager;
import org.semanticweb.owlapi.profiles.OWL2DLProfile;
import org.semanticweb.owlapi.profiles.OWLProfileReport;
import org.semanticweb.owlapi.reasoner.OWLReasoner;

public class VerifyOntology {
        private static final Map<String, String> COMPLIANCE_CLASSES = Map.ofEntries(
        Map.entry("VeganDiet", "VeganDish"),
        Map.entry("VegetarianDiet", "VegetarianDish"),
        Map.entry("PescatarianDiet", "PescatarianDish"),
        Map.entry("HalalDiet", "HalalCompatibleDish"),
        Map.entry("KosherDiet", "KosherCompatibleDish"),
        Map.entry("NutAllergy", "NutFreeDish"),
        Map.entry("GlutenIntolerance", "GlutenFreeDish"),
        Map.entry("LactoseIntolerance", "LactoseFreeDish"),
        Map.entry("PeanutAllergy", "PeanutFreeDish"),
        Map.entry("SoyAllergy", "SoyFreeDish"),
        Map.entry("EggAllergy", "EggFreeDish"),
        Map.entry("ShellfishAllergy", "ShellfishFreeDish"),
        Map.entry("FishAllergy", "FishFreeDish")
    );
    
    private static final String LEGACY_CUSTOMER = "http://webprotege.stanford.edu/RBm263Lg2Mmwf39Po96cwhj";

    private final OWLReasoner reasoner;
    private final OWLDataFactory factory;
    private final String namespace;
    private final Map<String, Set<String>> facts = new HashMap<>();

    private VerifyOntology(OWLReasoner reasoner, OWLDataFactory factory, String namespace) {
        this.reasoner = reasoner;
        this.factory = factory;
        this.namespace = namespace;
    }

    private OWLClass cls(String name) {
        return factory.getOWLClass(IRI.create(namespace + name));
    }

    private Set<OWLNamedIndividual> instances(OWLClass type) {
        return reasoner.getInstances(type, false).getFlattened();
    }

    private Set<OWLNamedIndividual> values(OWLNamedIndividual subject, String property) {
        return reasoner.getObjectPropertyValues(
            subject, factory.getOWLObjectProperty(IRI.create(namespace + property))
        ).getFlattened();
    }

    private static String id(OWLNamedIndividual individual) {
        return individual.getIRI().getShortForm();
    }

    private void add(String relation, String... columns) {
        facts.computeIfAbsent(relation, name -> new TreeSet<>()).add(String.join(",", columns));
    }

    private void evaluate(Path output) throws IOException {
        Set<OWLNamedIndividual> dishes = instances(cls("Dish"));
        Set<OWLNamedIndividual> complete = instances(cls("CompleteRecipe"));
        Set<OWLNamedIndividual> spicy = instances(cls("SpicyDish"));
        Set<OWLNamedIndividual> customers = instances(factory.getOWLClass(IRI.create(LEGACY_CUSTOMER)));
        Map<String, Set<OWLNamedIndividual>> compliant = new HashMap<>();
        for (Map.Entry<String, String> entry : COMPLIANCE_CLASSES.entrySet()) {
            Set<OWLNamedIndividual> instances = instances(cls(entry.getValue()));
            compliant.put(entry.getKey(), instances);
            for (OWLNamedIndividual dish : instances) {
                add("complies", id(dish), entry.getKey());
            }
        }
        for (OWLNamedIndividual dish : instances(cls("MenuDish"))) {
            add("menuDish", id(dish));
        }
        for (OWLNamedIndividual dish : instances(cls("DairyFreeDish"))) {
            add("dairyFree", id(dish));
        }
        for (OWLNamedIndividual dish : instances(cls("HalalWithFixtureException"))) {
            add("halalWithFixtureException", id(dish));
        }
        if (reasoner.isSatisfiable(cls("VegetarianSalamiDish"))) {
            throw new IllegalStateException("The vegetarian salami class should be unsatisfiable");
        }
        Set<OWLClass> unsatisfiable = reasoner.getUnsatisfiableClasses().getEntitiesMinusBottom();
        if (!unsatisfiable.equals(Set.of(cls("VegetarianSalamiDish")))) {
            throw new IllegalStateException("Unexpected unsatisfiable classes: " + unsatisfiable);
        }
        add("unsatisfiable", "VegetarianSalamiDish");

        Map<OWLNamedIndividual, Set<OWLNamedIndividual>> ingredientCategories = new HashMap<>();
        for (OWLNamedIndividual dish : dishes) {
            Set<OWLNamedIndividual> contained = values(dish, "contains");
            Set<OWLNamedIndividual> violations = values(dish, "violatesRestriction");
            for (OWLNamedIndividual ingredient : contained) {
                add("containsIngredient", id(dish), id(ingredient));
                Set<OWLNamedIndividual> categories = ingredientCategories.computeIfAbsent(
                    ingredient, item -> values(item, "ingredientCategory")
                );
                if (spicy.contains(dish) && values(ingredient, "hasSpiciness").stream()
                        .anyMatch(level -> id(level).equals("HotSpicinessLevel"))) {
                    add("spicyBecause", id(dish), id(ingredient));
                }
                for (OWLNamedIndividual restriction : violations) {
                    if (values(restriction, "forbids").stream().anyMatch(categories::contains)) {
                        add("violation", id(dish), id(restriction), id(ingredient));
                    }
                }
            }
            for (OWLNamedIndividual customer : customers) {
                Set<OWLNamedIndividual> restrictions = values(customer, "hasRestriction");
                String decision = "unknownFor";
                if (restrictions.stream().anyMatch(violations::contains)) {
                    decision = "unsafeFor";
                } else if (complete.contains(dish) && restrictions.stream()
                        .allMatch(restriction -> compliant.get(id(restriction)).contains(dish))) {
                    decision = "safeFor";
                }
                add(decision, id(dish), id(customer));
            }
        }

        Files.createDirectories(output);
        for (Map.Entry<String, Set<String>> result : facts.entrySet()) {
            Files.write(output.resolve(result.getKey() + ".csv"), result.getValue());
        }
        System.out.printf("OWL 2 DL, consistent. %d menu dishes, %d evaluation dishes, %d customers.%n",
            facts.get("menuDish").size(), dishes.size() - facts.get("menuDish").size(), customers.size());
        System.out.println("Named classes: " + reasoner.getRootOntology().getClassesInSignature().stream()
            .filter(type -> !type.isBuiltIn()).count());
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("Usage: VerifyOntology <ontology.rdf> <output-directory>");
        }
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        OWLOntology ontology = manager.loadOntologyFromOntologyDocument(Path.of(args[0]).toFile());
        OWLProfileReport profile = new OWL2DLProfile().checkOntology(ontology);
        if (!profile.isInProfile()) {
            throw new IllegalStateException(profile.toString());
        }
        OWLReasoner reasoner = new ReasonerFactory().createReasoner(ontology);
        try {
            if (!reasoner.isConsistent()) {
                throw new IllegalStateException("The ontology is inconsistent");
            }
            String namespace = ontology.getOntologyID().getOntologyIRI().get() + "#";
            new VerifyOntology(reasoner, manager.getOWLDataFactory(), namespace).evaluate(Path.of(args[1]));
        } finally {
            reasoner.dispose();
        }
    }
}
