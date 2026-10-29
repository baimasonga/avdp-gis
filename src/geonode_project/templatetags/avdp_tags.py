"""Template helpers for the AVDP pages."""

from django import template

from geonode.base.models import ThesaurusKeyword

register = template.Library()

# Order and short descriptions for the homepage theme tiles. Concept ids match
# thesauri/avdp-categories.rdf; labels come from the loaded thesaurus.
THEMES = (
    ("crop-production", "Farm plots, crops and production"),
    ("farmer-organizations", "Groups, cooperatives, associations"),
    ("rural-infrastructure", "Feeder roads and access"),
    ("water-infrastructure", "Water points and irrigation"),
    ("storage-facilities", "Grain stores and warehouses"),
    ("input-distribution", "Seed, fertiliser and tools"),
    ("demonstration-extension", "Demonstration plots and extension"),
)


@register.simple_tag
def avdp_themes():
    """Return [{id, slug, label, description}] for the AVDP dataset categories."""
    keywords = {
        k.alt_label: k
        for k in ThesaurusKeyword.objects.filter(thesaurus__identifier="avdp-categories").prefetch_related("keyword")
    }
    themes = []
    for slug, description in THEMES:
        keyword = keywords.get(slug)
        if keyword is None:
            continue
        label = next((lbl.label for lbl in keyword.keyword.all() if lbl.lang == "en"), slug.replace("-", " ").title())
        themes.append({"id": keyword.id, "slug": slug, "label": label, "description": description})
    return themes
