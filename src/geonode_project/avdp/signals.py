"""Style newly uploaded vector datasets automatically (see avdp.smart_mapping).

After styling, the automatic data check (avdp/quality.py) runs and its report
is shown on the dataset's map page.

The GeoNode importer finishes an upload inside its Celery task
``geonode.upload.import_orchestrator`` and marks the ExecutionRequest as
finished with a queryset ``update()``, which sends no Django model signal.
So the hook listens for that task's Celery ``task_success`` signal and checks
whether the execution it worked on is now a finished upload. The new
datasets then get AVDP smart styles instead of GeoServer's generic default.

Disabled with AVDP_AUTO_STYLE=False. Failures are logged and never affect
the upload itself.
"""

import logging

from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger(__name__)

ORCHESTRATOR_TASK = "geonode.upload.import_orchestrator"
STYLED_ACTIONS = ("upload", "replace", "upsert")


def _execution_id(args, kwargs):
    if kwargs and kwargs.get("execution_id"):
        return kwargs["execution_id"]
    return args[1] if args and len(args) > 1 else None


def on_task_success(sender=None, **_kwargs):
    if getattr(sender, "name", None) != ORCHESTRATOR_TASK or not getattr(settings, "AVDP_AUTO_STYLE", True):
        return
    try:
        exec_id = _execution_id(sender.request.args, sender.request.kwargs)
        if exec_id:
            style_execution(exec_id)
    except Exception:
        logger.exception("AVDP smart style hook failed")


def style_execution(exec_id):
    from geonode.layers.models import Dataset
    from geonode.resource.models import ExecutionRequest
    from geonode.upload.models import ResourceHandlerInfo
    from geonode_project.avdp import history, quality, smart_mapping

    execution = ExecutionRequest.objects.filter(exec_id=exec_id).first()
    if not execution or execution.status != ExecutionRequest.STATUS_FINISHED:
        return
    if execution.action not in STYLED_ACTIONS:
        return
    # The orchestrator task can succeed more than once for an execution; style it once.
    if not _cache().add(_key(exec_id), 1, timeout=24 * 3600):
        return
    ids = ResourceHandlerInfo.objects.filter(execution_request=execution).values_list("resource_id", flat=True)
    for dataset in Dataset.objects.filter(resourcebase_ptr_id__in=list(ids)):
        try:
            result = smart_mapping.apply(dataset)
            logger.info("AVDP smart style for %s: %s", dataset.alternate, result)
        except Exception:
            logger.exception("AVDP smart style failed for %s", dataset.alternate)
        try:
            history.enable(dataset)
        except Exception:
            logger.exception("AVDP change history not enabled for %s", dataset.alternate)
        try:
            result = quality.run_and_save(dataset)
            logger.info("AVDP data check for %s: %s", dataset.alternate, result["summary"])
        except Exception:
            logger.exception("AVDP data check failed for %s", dataset.alternate)


def _cache():
    # The shared memcached cache: Celery runs several worker processes.
    return caches["memcached"] if "memcached" in settings.CACHES else caches["default"]


def _key(exec_id):
    return f"avdp-smart-style-{exec_id}"


def suppress(exec_id):
    """Skip the automatic style and data check for one upload (for commands that do their own)."""
    _cache().set(_key(exec_id), 1, timeout=24 * 3600)


def connect():
    from celery.signals import task_success

    task_success.connect(on_task_success, weak=False, dispatch_uid="avdp_smart_style")
