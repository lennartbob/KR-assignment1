# SafeSlice

SafeSlice compares OWL 2 DL and Datalog on a restaurant menu with 16 dishes. Both implementations derive ingredient chains and check the recorded restrictions for the same customer profiles.

- [data](data) holds the eleven shared CSVs. Edit recipe and restriction facts here. `ingredient_types.csv`, `type_hierarchy.csv` and `type_categories.csv` define the ingredient taxonomy, `dish_types.csv` gives each dish its type, and `dish_calories.csv` gives each menu dish an illustrative energy value.
- [code.rdf](code.rdf) is the generated ontology to open in desktop Protégé. Select HermiT under **Reasoner** and start it. In **DL Query**, try `MenuDish and VeganDish`, `MenuDish and NutFreeDish`, or `MenuDish and (contains value Milk)`. Select **Instances** to see menu entries.
- [datalog/safeslice.rls](datalog/safeslice.rls) is the Nemo program. The predicate `containsIngredient` corresponds to OWL's `contains`.
- [report/main.tex](report/main.tex) records the results for all 14 competency questions. [SafeSlice_pack](SafeSlice_pack) contains the original project materials, and [ontology](ontology) preserves the imported WebProtégé baseline.

## Reproduce the comparison

Use Python 3.9 or later, Protégé 5.6.9 with its HermiT plugin, a Java 11 or later JDK, and Nemo 0.10.1. Run from the repository root:

```powershell
python tools/build_ontology.py
python tools/build_ontology.py --check
python tools/verify_owl.py 'C:/path/to/Protege-5.6.9' build/owl
Push-Location datalog
nmo.exe --overwrite-results --export-dir ../build/nemo safeslice.rls
Pop-Location
python tools/compare_results.py build/owl build/nemo
```

`verify_owl.py` takes the Protégé folder containing `bundles` and `plugins`. If only Protégé's bundled Java runtime is available, pass `--java` with its Java executable and `--compiler` with an Eclipse ECJ jar that supports Java 11. On Linux and macOS, use `nmo` and the equivalent directory changes. Run Nemo from `datalog` so the CSV imports resolve.

Without Protégé, `python tools/verify_owl_owlready.py build/owl` can replace the `verify_owl.py` step. It needs `pip install owlready2` and a Java runtime, uses the HermiT version bundled with owlready2, and also exports the classes that use the ingredient taxonomy and the constructs beyond ALC. It does not run the OWL 2 DL profile check.

A category in `type_categories.csv` holds for every ingredient of that type and its subtypes, so `categories.csv` lists only what is specific to one ingredient. OWL infers the inherited categories from subclass axioms, and the Datalog program walks the hierarchy with explicit rules.

The Datalog relations `compositionCycle`, `pizzaBaseProblem`, `twoBases` and `twoTypes` are integrity checks and should stay empty. The matching OWL axioms make the ontology inconsistent when the data breaks them.

`categories.csv` marks complete recipes and evaluation fixtures. A complete recipe receives closure axioms in OWL and can receive a positive compliance result in both engines. The unknown dressing is evaluated separately from the menu. The two gelatin fixtures compare a hypothetical certification exception with the baseline rule, which blocks pork. The sample recipes and policies are the working coursework dataset.
