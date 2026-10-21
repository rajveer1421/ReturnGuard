"""Visual inspection agent: one multimodal call that sees all six photos.

Deliberately *not* told the embedding scores or the identity result, so its
verdict is an independent piece of evidence rather than an echo of earlier
stages. The prompt is neutral: it never says the items are the same product."""
from returnguard import config, llm
from returnguard.schemas import VisualInspection

SYSTEM = """You are the visual inspection agent of an e-commerce return-verification system.
You get photos of a product taken by the delivery agent at handover (DELIVERY) and photos of the item the
customer is returning now (RETURN), each from the front, back and side. Backgrounds were removed automatically;
ignore the grey background and small cut-out errors at the edges.

Decide whether the RETURN item is the same physical unit that was delivered.

Judge the product itself only. Do NOT count differences in lighting, exposure, white balance, camera angle,
rotation, zoom, focus or cropping: a second photo of the same item taken days later always differs in these.

Signs of a DIFFERENT unit:
- different colour of the product material, different shape, proportions or parts (lid, buttons, compartments)
- printed labels or logos that differ, or that were present at delivery and are gone now
- wear, rust or scratches present at delivery that are absent now (the return looks newer than what was delivered)
- a different wear pattern, or accessories swapped
Signs of NEW DAMAGE on the same unit: scratches, dents, cracks or stains not visible in the delivery photos.
Signs of USE (the same unit was used or worn, then returned): stains, sweat or makeup marks, wear creases, pilling,
broken or missing beads and mirror-work, and tags that were attached at delivery but are now cut or missing.

Be decisive when the evidence is clear. Use 'inconclusive' only when the photos genuinely cannot tell."""

CATEGORY_NOTES = {
    "apparel": ("Garments are often folded at delivery and spread out at return, which can reveal hems, borders "
                "and patterns that were hidden. Compare the central pattern, colours, labels and cut instead. "
                "Festive and ethnic wear (chaniya choli, kediyu, lehenga) is often worn once for an event and "
                "returned: look closely for missing tags, makeup or kumkum on necklines, sweat marks, crushed "
                "pleats and loose mirrors, tassels or beads."),
    "electronics": "Internal faults are invisible in photos; judge only the exterior.",
}


def inspect(delivery_cutouts: dict, return_cutouts: dict, fingerprint: dict | None, category: str,
            reason_text: str) -> tuple[VisualInspection, llm.CallRecord]:
    context = [f"Product category: {category}.", f"Customer's stated return reason: {reason_text}."]
    if category in CATEGORY_NOTES:
        context.append(CATEGORY_NOTES[category])
    if fingerprint:
        marks = "; ".join(f"{m['description']} ({m['view']})" for m in fingerprint.get("distinctive_marks", []))
        acc = ", ".join(fingerprint.get("accessories", []))
        tags = ", ".join(fingerprint.get("tags_attached", []))
        if marks:
            context.append(f"Marks recorded on the delivered unit: {marks}.")
        if acc:
            context.append(f"Accessories delivered with it: {acc}.")
        if tags:
            context.append(f"Tags attached at delivery: {tags}.")

    parts = [llm.text_part("\n".join(context))]
    for angle in config.ANGLES:
        parts += [llm.text_part(f"DELIVERY {angle} view:"), llm.image_part(delivery_cutouts[angle], max_side=768),
                  llm.text_part(f"RETURN {angle} view:"), llm.image_part(return_cutouts[angle], max_side=768)]
    return llm.call_structured("visual_inspector", VisualInspection, SYSTEM, parts)
