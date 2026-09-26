from django.contrib import admin
from .models import (
    ClassCourse, ScheduleEntry, Conflict, SwapRequest, Substitute
)


@admin.register(ScheduleEntry)
class ScheduleEntryAdmin(admin.ModelAdmin):
    list_display = (
        'semester', 'class_id', 'course', 'teacher', 'day_of_week',
        'period', 'classroom', 'is_locked', 'is_conflict'
    )
    list_filter = ('semester', 'day_of_week', 'period', 'is_locked', 'is_conflict')
    search_fields = ('class_id__name', 'course__name', 'teacher__name')


@admin.register(Substitute)
class SubstituteAdmin(admin.ModelAdmin):
    list_display = (
        'affected_entry', 'original_teacher', 'substitute_teacher',
        'start_date', 'end_date', 'is_active'
    )
    list_filter = ('is_active', 'start_date', 'end_date', 'semester')
    search_fields = (
        'original_teacher__name', 'substitute_teacher__name',
        'affected_entry__class_id__name', 'affected_entry__course__name'
    )


admin.site.register(ClassCourse)
admin.site.register(Conflict)
admin.site.register(SwapRequest)
