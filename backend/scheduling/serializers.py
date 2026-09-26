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
    teacher_name = serializers.CharField(source='teacher.name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    class_name = serializers.CharField(source='class_id.name', read_only=True)
    original_teacher_name = serializers.SerializerMethodField()
    is_substituted = serializers.SerializerMethodField()
    effective_teacher = serializers.SerializerMethodField()
    effective_teacher_name = serializers.SerializerMethodField()
    substitute_start_date = serializers.SerializerMethodField()
    substitute_end_date = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleEntry
        fields = '__all__'

    def _active_substitute(self, obj):
        # 由视图按参考日期挂载（_active_substitute），表示当天生效的代课记录
        return getattr(obj, '_active_substitute', None)

    def get_is_substituted(self, obj):
        return self._active_substitute(obj) is not None

    def get_effective_teacher(self, obj):
        sub = self._active_substitute(obj)
        return sub.substitute_teacher_id if sub else obj.teacher_id

    def get_effective_teacher_name(self, obj):
        sub = self._active_substitute(obj)
        return sub.substitute_teacher.name if sub else obj.teacher.name

    def get_original_teacher_name(self, obj):
        sub = self._active_substitute(obj)
        if sub:
            return obj.teacher.name
        if obj.original_teacher:
            return obj.original_teacher.name
        return None

    def get_substitute_start_date(self, obj):
        sub = self._active_substitute(obj)
        return sub.start_date if sub else None

    def get_substitute_end_date(self, obj):
        sub = self._active_substitute(obj)
        return sub.end_date if sub else None


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
    course_name = serializers.CharField(
        source='affected_entry.course.name', read_only=True
    )
    class_name = serializers.CharField(
        source='affected_entry.class_id.name', read_only=True
    )
    day_of_week = serializers.IntegerField(
        source='affected_entry.day_of_week', read_only=True
    )
    period = serializers.IntegerField(
        source='affected_entry.period', read_only=True
    )

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
    reason = serializers.CharField(allow_blank=True, default='')

    def validate(self, data):
        if data['end_date'] < data['start_date']:
            raise serializers.ValidationError(
                {'end_date': '结束日期不能早于开始日期'}
            )
        return data
