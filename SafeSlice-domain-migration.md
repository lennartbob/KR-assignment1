# SafeSlice restaurant menu migration plan

SafeSlice will answer **Can this customer eat this dish under their recorded dietary restrictions?** The menu expands from pizza to a mixed restaurant menu. The same ingredient chains, restriction rules, six CSV tables, and competency questions will drive the OWL and Datalog implementations. The team will approve the dish list and recipe facts at the next meeting.

## Starting point

- [Local ontology](code.rdf) contains the 67 named classes migrated from WebProtégé revision 229, with labels and subclass links. Its property declarations, menu and customer individuals, and compliance axioms still need to be implemented. The repository also has no Nemo rules file yet.
- [Sai’s project pack](SafeSlice_pack/) contains the original design, 14 competency questions, and sample data. Use the [terminology draft](SafeSlice_pack/tex_sources/01_terms.tex), [competency questions](SafeSlice_pack/tex_sources/03_competency_questions.tex), and [implementation draft](SafeSlice_pack/tex_sources/04_data_and_implementation.tex) alongside the [project notes](SafeSlice_pack/docs/SafeSlice_KR_notes.docx). The original pack is the baseline for the migration.
- The [shared Overleaf project](https://www.overleaf.com/project/6aec3cf8758328692b26d0c2) currently has a starter `main.tex`. Use it for the report. Keep the data, ontology, and rule code in Git and cite the tested commit in the report.

## Proposed menu for the next meeting

The four pizzas preserve existing examples. Each proposed recipe below is a fixture for this menu, with its ingredients to be agreed by the team.

| Dish ID | Recipe fact or comparison to preserve |
| --- | --- |
| `MargheritaPizza` | Normal dough reaches gluten through wheat flour. Specify the mozzarella’s rennet for the vegetarian question. |
| `PestoSpecialePizza` | Pesto reaches pine nuts and reaches milk through Parmesan. |
| `VeganGardenPizza` | A complete plant-based recipe provides a positive vegan and dairy-free case. |
| `TonnoPizza` | Tuna provides the original explanation for a vegetarian violation. |
| `PorkShoyuRamen` | Wheat-containing soy sauce reaches gluten. Pork broth independently reaches pork. |
| `ThaiGreenCurry` | The chosen curry sauce contains fish sauce made with anchovy. Chili provides the spicy explanation. |
| `BeefBurger` | The chosen bun contains wheat flour. The patty adds a meat case independent of the bun. |
| `CreamyMushroomPasta` | Cream sauce reaches milk. The pasta provides a separate wheat or egg example if the chosen recipe contains them. |
| `TofuRiceBowl` | Compare a documented wheat-free dressing with a test variant whose dressing composition is unknown. |
| `CashewVegetableStirFry` | Cashew sauce gives a nut violation in a dish with no listed meat. |
| `ChickpeaTomatoStew` | A complete recipe with no matching blockers provides a positive control for combining Omar’s two restrictions. |

At the meeting, agree on the recipes and the vocabulary for restrictions. In particular, record whether the existing milk/dairy proxy for lactose stays a simplification or gets an explicit `Lactose` component. Keep halal and kosher scoped to the rules represented in the project. Settle Q13’s hypothetical certification exception and its precedence over a recorded pork blocker before encoding it in either engine.

## Implementation order

1. **Agree on identifiers and preserve the baseline.** Replace pizza as the scope of the rules with a new `Dish` class. Give the existing `Pizzas` class the singular label `Pizza` and keep its IRI as a subtype of `Dish`. Record the mapping from existing OWL labels and IRIs to agreed CSV IDs, for example `Ingrediënts` → `Ingredient` and `Tomota_Sauce` → `TomatoSauce`. Use named menu and recipe individuals for facts from CSV. Map retained pizza classes to the appropriate menu individuals through class assertions. Count distinct terms after the menu is agreed, including each defined class once, and check the result against the assignment’s vocabulary requirement.
2. **Update one shared dataset.** Rename `pizzas.csv` to `dish_ingredients.csv` and change `pizza,topping` to `dish,ingredient`. In `bases.csv`, change `pizza,base` to `dish,base` and allow a dish to have no separate base. Retain `madefrom.csv`, `categories.csv`, `restrictions.csv`, and `customers.csv` with their current two-column structure. Store each direct recipe or base edge once. Put the chosen sauce, broth, and dough compositions in `madefrom.csv`. Define which recipes are complete and keep the missing-composition and certification cases as explicit test fixtures shared by both implementations. Treat `tom,None` as a known customer with zero restrictions during import.
3. **Implement and check the rules in both engines.** Use `hasIngredient` for direct recipe links and `hasBase` as a more specific ingredient link. Derive `contains` from both and follow `madeFrom` to reach hidden components. Keep the rule that any recorded restriction violation makes the dish unsuitable for that customer. Use the same ingredient categories and restriction facts in both engines. Classify ingredient categories explicitly, including plant-based cheese separately from dairy.

   - **Protégé and HermiT (Merijn and Lennart, as proposed in Sai’s pack).** Start with the ramen and pesto chains. Check that the property axioms are valid in OWL 2 DL and that HermiT infers both paths. Keep cardinality constraints off the chain-derived `contains` property. Use positive entailments to detect forbidden ingredients. Require closure and sufficient category evidence before claiming a positive restriction match. Check customer profiles by combining restriction-specific class queries where the Datalog rule has no direct OWL equivalent. Keep the deliberately unsatisfiable salami example as an uninstantiated test class so the main ontology stays consistent. [OWL 2 Primer](https://www.w3.org/TR/owl2-primer/) · [OWL 2 DL global restrictions](https://www.w3.org/TR/owl-syntax/#Global_Restrictions_on_Axioms_in_OWL_2_DL)
   - **Nemo (Sai and Jasper, as proposed in the pack).** Import the same rows, explicitly skip headers, and check that imported IDs match the rule constants. Derive recursive `contains` before evaluating violations and stratified negation. Use Nemo’s absence-of-blocker result for the open-world comparison, and keep it distinguishable from a positive compliance result based on complete recipe data. Use a separate validation result for the salami contradiction if the team wants a Datalog counterpart. [Nemo CSV imports](https://knowsys.github.io/nemo-doc/reference/imports/) · [Nemo negation](https://knowsys.github.io/nemo-doc/intro/tour/#negation)
4. **Run the same cases and write the report.** Check duplicate edges, inconsistent identifiers, and missing reference data before importing. Record expected result, actual OWL result, actual Nemo result, evidence path, and modelling effort for each competency question. Use the shared Overleaf `main.tex` for the report, drawing from the pack’s five standalone TeX drafts. Move reusable section bodies into inputs as needed and carry over their package requirements, especially TikZ and forest for the diagrams. Report the agreed scope, rule semantics, representative derivations, and the comparison of complete versus incomplete recipes. [Overleaf main document guidance](https://docs.overleaf.com/getting-started/recompiling-your-project/the-main-document)

## Evaluation cases to carry forward

| Original questions | Restaurant menu checks |
| --- | --- |
| Q1–Q5 | List dishes for Anna and Omar, list dishes without nuts under the agreed completeness policy, classify Margherita under the agreed recipe, and find direct and indirect milk. Check that either of Omar’s restrictions can block a dish. |
| Q6–Q9 | Explain the curry’s spiciness, return pesto’s nested ingredients, exclude Pesto Speciale from nut-free results, and check the complete Vegan Garden recipe for dairy. |
| Q10–Q11 | Confirm the deliberately impossible vegetarian salami class and trace a normal dough pizza to gluten. Repeat the gluten check on the non-pizza ramen. |
| Q12–Q14 | Compare the result for the unknown dressing, test the agreed hypothetical pork-gelatin certification rule, and retain the tuna explanation. Add a second explanation for anchovy through the curry’s fish sauce. |

The migration is ready to implement once the team approves the menu, ingredient IDs, and policy choices. It is complete when the local ontology and Nemo rules use the same revised CSVs, both runs are recorded for all 14 competency questions, and the Overleaf report builds with evidence from that Git revision.
