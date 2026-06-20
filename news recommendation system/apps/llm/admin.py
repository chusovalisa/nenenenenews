from django.contrib import admin

from apps.llm.models import LLMClaim, LLMProvider, LLMResponse

admin.site.register(LLMProvider)
admin.site.register(LLMResponse)
admin.site.register(LLMClaim)
