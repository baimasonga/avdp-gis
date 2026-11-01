"""Small JSON views used by the AVDP pages."""

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import render

from geonode.base.models import ResourceBase
from geonode.security.utils import get_visible_resources


def change_history(request, pk):
    """Recent changes to a dataset's records, for users who may download its data."""
    from geonode.layers.models import Dataset
    from geonode_project.avdp import history

    resource = get_visible_resources(ResourceBase.objects.filter(pk=pk), request.user).first()
    dataset = Dataset.objects.filter(pk=pk).first() if resource else None
    if dataset is None:
        raise Http404("Dataset not found.")
    if not request.user.has_perm("download_resourcebase", dataset.get_self_resource()):
        raise PermissionDenied("You may not see this dataset's records.")
    return render(
        request,
        "avdp/history.html",
        {"dataset": dataset, "entries": history.entries(dataset), "tracked": history.is_enabled(dataset)},
    )


def quality_report(request, pk):
    """The latest data check of a dataset, for users who may view the dataset."""
    visible = get_visible_resources(ResourceBase.objects.filter(pk=pk), request.user)
    resource = visible.first()
    report = getattr(resource, "avdp_quality", None) if resource else None
    if report is None:
        raise Http404("No data check for this resource.")
    return JsonResponse(
        {
            "resource": resource.pk,
            "status": report.status,
            "summary": report.summary,
            "checked": report.checked.isoformat(),
            **report.report,
        }
    )
