from rest_framework import serializers
from .models import (
    ClassCourse, ScheduleEntry, Conflict, SwapRequest, Substitute
)


class ClassCourseSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    teacher_name = serializers.CharField(source='teacher.name', read_only=True)
    class_name = serializers.CharField(source='class_id.name', read_only=True)
    weekly_hours = serializers.IntegerField(source='course.weekly_hours', read_only=True)

    class Meta:
        model = ClassCourse
        fields = '__all__'


class ScheduleEntrySerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    teacher_name = serializers.CharField(source='teacher.name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    class_name = serializers.CharField(source='class_id.name', read_only=True)

    class Meta:
        model = ScheduleEntry
        fields = '__all__'


class ScheduleEntryDetailSerializer(serializers.ModelSerializer):
    course_name = serializers.CharField(source='course.name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    class_name = serializers.CharField(source='class_id.name', read_only=True)
    effective_teacher = serializers.SerializerMethodField()
    effective_teacher_name = serializers.SerializerMethodField()
    scheduled_teacher = serializers.SerializerMethodField()
    scheduled_teacher_name = serializers.SerializerMethodField()
    original_teacher = serializers.SerializerMethodField()
    original_teacher_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()
    has_active_substitute = serializers.SerializerMethodField()
    substitute_start_date = serializers.SerializerMethodField()
    substitute_end_date = serializers.SerializerMethodField()
    substitute_reason = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleEntry
        fields = '__all__'

    def _schedule_date(self):
        return self.context.get('schedule_date')

    def _active_substitute(self, obj):
        return obj.active_substitute(self._schedule_date())

    def get_effective_teacher(self, obj):
        return obj.effective_teacher(self._schedule_date()).id

    def get_effective_teacher_name(self, obj):
        return obj.effective_teacher(self._schedule_date()).name

    def get_scheduled_teacher(self, obj):
        return obj.scheduled_teacher().id

    def get_scheduled_teacher_name(self, obj):
        return obj.scheduled_teacher().name

    def get_original_teacher(self, obj):
        return obj.scheduled_teacher().id

    def get_original_teacher_name(self, obj):
        return obj.scheduled_teacher().name

    def get_teacher_name(self, obj):
        return obj.effective_teacher(self._schedule_date()).name

    def get_has_active_substitute(self, obj):
        return self._active_substitute(obj) is not None

    def get_substitute_start_date(self, obj):
        substitute = self._active_substitute(obj)
        return substitute.start_date.isoformat() if substitute else None

    def get_substitute_end_date(self, obj):
        substitute = self._active_substitute(obj)
        return substitute.end_date.isoformat() if substitute else None

    def get_substitute_reason(self, obj):
        substitute = self._active_substitute(obj)
        return substitute.reason if substitute else None


class ConflictSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conflict
        fields = '__all__'


class SwapRequestSerializer(serializers.ModelSerializer):
    requesting_teacher_name = serializers.CharField(
        source='requesting_teacher.name', read_only=True
    )
    target_teacher_name = serializers.CharField(
        source='target_teacher.name', read_only=True
    )

    class Meta:
        model = SwapRequest
        fields = '__all__'


class SubstituteSerializer(serializers.ModelSerializer):
    original_teacher_name = serializers.CharField(
        source='original_teacher.name', read_only=True
    )
    substitute_teacher_name = serializers.CharField(
        source='substitute_teacher.name', read_only=True
    )
    course_name = serializers.CharField(source='affected_entry.course.name', read_only=True)
    class_name = serializers.CharField(source='affected_entry.class_id.name', read_only=True)
    day_of_week = serializers.IntegerField(source='affected_entry.day_of_week', read_only=True)
    period = serializers.IntegerField(source='affected_entry.period', read_only=True)

    class Meta:
        model = Substitute
        fields = '__all__'


class AutoScheduleRequestSerializer(serializers.Serializer):
    semester_id = serializers.IntegerField()
    respect_locked = serializers.BooleanField(default=True)


class ConflictCheckSerializer(serializers.Serializer):
    semester_id = serializers.IntegerField()


class SwapScheduleRequestSerializer(serializers.Serializer):
    entry1_id = serializers.IntegerField()
    entry2_id = serializers.IntegerField()
    reason = serializers.CharField(required=False)


class SubstituteRequestSerializer(serializers.Serializer):
    entry_id = serializers.IntegerField()
    substitute_teacher_id = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField()

    def validate(self, attrs):
        if attrs['end_date'] < attrs['start_date']:
            raise serializers.ValidationError({'end_date': '结束日期不能早于开始日期。'})
        return attrs
