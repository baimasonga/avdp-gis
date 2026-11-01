"""Small JSON views used by the AVDP pages."""

from django.http import Http404, JsonResponse

from geonode.base.models import ResourceBase
from geonode.security.utils import get_visible_resources


def quality_report(request, pk):
    """The latest data check of a dataset, for users who may view the dataset."""
    visible = get_visible_resources(ResourceBase.objects.filter(pk=pk), request.user)
    resource = visible.first()
    report = getattr(resource, "avdp_quality", None) if resource else None
    if report is None:
        raise Http404("No data check for this resource.")
    return JsonResponse(
        {"status": report.status, "summary": report.summary, "checked": report.checked.isoformat(), **report.report}
    )
