from django.contrib import admin

from apps.factcheck.models import Evidence, FactCheckResult

admin.site.register(FactCheckResult)
admin.site.register(Evidence)
