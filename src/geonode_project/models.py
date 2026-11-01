"""AVDP additions to the GeoNode data model."""

from django.db import models


class QualityReport(models.Model):
    """The latest automatic data check of a dataset (see avdp/quality.py)."""

    STATUS_CHOICES = [("ok", "No issues"), ("warnings", "Warnings"), ("problems", "Problems")]

    resource = models.OneToOneField("base.ResourceBase", on_delete=models.CASCADE, related_name="avdp_quality")
    checked = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    summary = models.CharField(max_length=255)
    report = models.JSONField(default=dict)

    class Meta:
        verbose_name = "AVDP data check"

    def __str__(self):
        return f"{self.resource_id}: {self.summary}"
