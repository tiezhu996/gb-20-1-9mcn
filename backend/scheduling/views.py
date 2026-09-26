from datetime import timedelta

from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.serializers import ValidationError
from django.db import transaction
from core.models import Semester, Classroom, Teacher, Class
from .models import (
    ClassCourse, ScheduleEntry, Conflict, SwapRequest, Substitute
)
from .serializers import (
    ClassCourseSerializer, ScheduleEntrySerializer,
    ScheduleEntryDetailSerializer, ConflictSerializer,
    SwapRequestSerializer, SubstituteSerializer,
    AutoScheduleRequestSerializer, ConflictCheckSerializer,
    SwapScheduleRequestSerializer, SubstituteRequestSerializer
)
from .csp_solver import CSPScheduler, ConflictDetector, SchedulingTask
from .pdf_export import (
    generate_class_timetable_pdf,
    generate_teacher_timetable_pdf,
    generate_classroom_timetable_pdf
)


def get_requested_date(request):
    raw_date = request.query_params.get('date')
    if not raw_date:
        return timezone.localdate()

    try:
        return timezone.datetime.fromisoformat(raw_date).date()
    except ValueError:
        raise ValidationError({'date': '日期格式必须为 YYYY-MM-DD。'})


def teacher_schedule_entries(semester, teacher, on_date):
    """返回某教师在指定日期实际相关的课：原任课和当天由其代课都包含。"""
    active_substitute = Q(
        substitute_records__is_active=True,
        substitute_records__substitute_teacher=teacher,
        substitute_records__start_date__lte=on_date,
        substitute_records__end_date__gte=on_date
    )
    return ScheduleEntry.objects.filter(
        Q(semester=semester)
        & (Q(teacher=teacher) | Q(original_teacher=teacher) | active_substitute)
    ).prefetch_related(
        Prefetch(
            'substitute_records',
            queryset=Substitute.objects.filter(is_active=True).select_related(
                'original_teacher', 'substitute_teacher'
            )
        )
    ).distinct()


def first_matching_weekday(start_date, end_date, day_of_week):
    first_date = start_date + timedelta(
        days=(day_of_week - start_date.isoweekday()) % 7
    )
    return first_date if first_date <= end_date else None


def has_matching_weekday(start_date, end_date, day_of_week):
    return first_matching_weekday(start_date, end_date, day_of_week) is not None


def is_semester_teaching_day(semester, on_date):
    if on_date < semester.start_date or on_date > semester.end_date:
        return False

    holiday_set = set()
    for holiday in semester.holidays or []:
        if isinstance(holiday, dict):
            holiday_date = holiday.get('date')
        else:
            holiday_date = holiday
        if holiday_date:
            try:
                holiday_set.add(timezone.datetime.fromisoformat(holiday_date).date())
            except (TypeError, ValueError):
                continue

    return on_date not in holiday_set


def find_substitute_conflict(entry, substitute_teacher, start_date, end_date):
    """查找代课老师在该时段、该日期范围内已经承担的其他课。"""
    overlapping_substitute = Q(
        substitute_records__is_active=True,
        substitute_records__substitute_teacher=substitute_teacher,
        substitute_records__start_date__lte=end_date,
        substitute_records__end_date__gte=start_date
    )
    candidates = ScheduleEntry.objects.filter(
        Q(semester=entry.semester)
        & Q(day_of_week=entry.day_of_week)
        & Q(period=entry.period)
        & (
            Q(teacher=substitute_teacher)
            | Q(original_teacher=substitute_teacher)
            | overlapping_substitute
        )
    ).exclude(id=entry.id).prefetch_related(
        'course', 'class_id', 'classroom', 'teacher', 'original_teacher',
        Prefetch(
            'substitute_records',
            queryset=Substitute.objects.filter(is_active=True).select_related(
                'original_teacher', 'substitute_teacher'
            )
        )
    ).distinct()

    for other_entry in candidates:
        current_date = first_matching_weekday(
            start_date, end_date, entry.day_of_week
        )
        while current_date is not None and current_date <= end_date:
            if (
                is_semester_teaching_day(entry.semester, current_date)
                and other_entry.effective_teacher(current_date) == substitute_teacher
            ):
                return other_entry, current_date
            current_date += timedelta(days=7)

    return None, None


class ClassCourseViewSet(viewsets.ModelViewSet):
    queryset = ClassCourse.objects.all()
    serializer_class = ClassCourseSerializer
    permission_classes = [AllowAny]


class ScheduleEntryViewSet(viewsets.ModelViewSet):
    queryset = ScheduleEntry.objects.all().select_related(
        'course', 'teacher', 'original_teacher', 'classroom', 'class_id', 'semester'
    ).prefetch_related(
        Prefetch(
            'substitute_records',
            queryset=Substitute.objects.filter(is_active=True).select_related(
                'original_teacher', 'substitute_teacher'
            )
        )
    )
    serializer_class = ScheduleEntryDetailSerializer
    permission_classes = [AllowAny]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request:
            context['schedule_date'] = get_requested_date(self.request)
        else:
            context['schedule_date'] = timezone.localdate()
        return context

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return ScheduleEntryDetailSerializer
        return ScheduleEntrySerializer

    @action(detail=False, methods=['get'])
    def by_semester(self, request):
        semester_id = request.query_params.get('semester_id')
        if not semester_id:
            return Response(
                {'error': 'semester_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        on_date = get_requested_date(request)
        entries = self.get_queryset().filter(semester_id=semester_id)
        serializer = ScheduleEntryDetailSerializer(
            entries, many=True, context={'request': request, 'schedule_date': on_date}
        )
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_class(self, request):
        semester_id = request.query_params.get('semester_id')
        class_id = request.query_params.get('class_id')
        on_date = get_requested_date(request)
        entries = self.get_queryset().filter(
            semester_id=semester_id, class_id=class_id
        )
        serializer = ScheduleEntryDetailSerializer(
            entries, many=True, context={'request': request, 'schedule_date': on_date}
        )
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_teacher(self, request):
        semester_id = request.query_params.get('semester_id')
        teacher_id = request.query_params.get('teacher_id')
        on_date = get_requested_date(request)
        teacher = get_object_or_404(Teacher, id=teacher_id)
        semester = get_object_or_404(Semester, id=semester_id)
        entries = teacher_schedule_entries(semester, teacher, on_date)
        serializer = ScheduleEntryDetailSerializer(
            entries, many=True, context={'request': request, 'schedule_date': on_date}
        )
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_classroom(self, request):
        semester_id = request.query_params.get('semester_id')
        classroom_id = request.query_params.get('classroom_id')
        on_date = get_requested_date(request)
        entries = self.get_queryset().filter(
            semester_id=semester_id, classroom_id=classroom_id
        )
        serializer = ScheduleEntryDetailSerializer(
            entries, many=True, context={'request': request, 'schedule_date': on_date}
        )
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def auto_schedule(self, request):
        req_serializer = AutoScheduleRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(req_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        semester_id = req_serializer.validated_data['semester_id']
        respect_locked = req_serializer.validated_data['respect_locked']

        try:
            semester = Semester.objects.get(id=semester_id)
        except Semester.DoesNotExist:
            return Response(
                {'error': 'Semester not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        class_courses = ClassCourse.objects.filter(
            semester=semester
        ).select_related('class_id', 'course', 'teacher')

        if not class_courses.exists():
            return Response(
                {'error': 'No class courses configured for this semester'},
                status=status.HTTP_400_BAD_REQUEST
            )

        tasks = []
        for cc in class_courses:
            tasks.append(SchedulingTask(
                class_id=cc.class_id.id,
                course_id=cc.course.id,
                teacher_id=cc.teacher.id,
                weekly_hours=cc.course.weekly_hours,
                preferred_room_type=cc.course.preferred_room_type,
                priority=cc.course.priority,
                available_time_slots=[],
                classroom_capacity=cc.class_id.student_count or 40
            ))

        classrooms_data = {
            c.id: {
                'room_type': c.room_type,
                'capacity': c.capacity,
                'name': c.name
            } for c in Classroom.objects.filter(is_active=True)
        }

        teachers_data = {
            t.id: {
                'name': t.name,
                'available_time_slots': t.available_time_slots if t.available_time_slots else []
            } for t in Teacher.objects.filter(is_active=True)
        }

        locked_entries = []
        if respect_locked:
            locked = ScheduleEntry.objects.filter(
                semester=semester, is_locked=True
            ).values(
                'id', 'class_id', 'teacher_id', 'classroom_id',
                'day_of_week', 'period', 'is_locked'
            )
            locked_entries = list(locked)

        scheduler = CSPScheduler(semester)
        assignments, scheduling_conflicts = scheduler.schedule(
            tasks, classrooms_data, teachers_data, locked_entries
        )

        with transaction.atomic():
            if respect_locked:
                ScheduleEntry.objects.filter(
                    semester=semester, is_locked=False
                ).delete()
            else:
                ScheduleEntry.objects.filter(semester=semester).delete()

            bulk_entries = []
            for a in assignments:
                if a.get('is_locked'):
                    continue
                bulk_entries.append(ScheduleEntry(
                    semester_id=a['semester_id'],
                    class_id_id=a['class_id'],
                    course_id=a['course_id'],
                    teacher_id=a['teacher_id'],
                    classroom_id=a['classroom_id'],
                    day_of_week=a['day_of_week'],
                    period=a['period'],
                    is_locked=False
                ))
            ScheduleEntry.objects.bulk_create(bulk_entries)

            all_entries = ScheduleEntry.objects.filter(
                semester=semester
            ).values('id', 'teacher_id', 'classroom_id', 'class_id', 'day_of_week', 'period')

            detector = ConflictDetector()
            conflicts = detector.detect_conflicts(list(all_entries))

            Conflict.objects.filter(semester=semester).delete()
            bulk_conflicts = []
            for c in conflicts:
                bulk_conflicts.append(Conflict(
                    semester=semester,
                    conflict_type=c['conflict_type'],
                    day_of_week=c['day_of_week'],
                    period=c['period'],
                    involved_entries=c['involved_entries'],
                    message=c['message']
                ))
            Conflict.objects.bulk_create(bulk_conflicts)

            for c in conflicts:
                for eid in c['involved_entries']:
                    try:
                        entry = ScheduleEntry.objects.get(id=eid)
                        entry.is_conflict = True
                        entry.conflict_type = c['conflict_type']
                        entry.save()
                    except ScheduleEntry.DoesNotExist:
                        pass

        final_entries = ScheduleEntry.objects.filter(semester=semester)
        serializer = ScheduleEntryDetailSerializer(final_entries, many=True)

        return Response({
            'schedule': serializer.data,
            'conflicts': conflicts,
            'scheduling_messages': scheduling_conflicts,
            'total_entries': len(serializer.data)
        })

    @action(detail=False, methods=['post'])
    def check_conflicts(self, request):
        req_serializer = ConflictCheckSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(req_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        semester_id = req_serializer.validated_data['semester_id']
        entries = ScheduleEntry.objects.filter(
            semester_id=semester_id
        ).values('id', 'teacher_id', 'classroom_id', 'class_id', 'day_of_week', 'period')

        detector = ConflictDetector()
        conflicts = detector.detect_conflicts(list(entries))

        return Response({'conflicts': conflicts})

    @action(detail=False, methods=['post'])
    def swap(self, request):
        req_serializer = SwapScheduleRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(req_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        entry1_id = req_serializer.validated_data['entry1_id']
        entry2_id = req_serializer.validated_data['entry2_id']
        reason = req_serializer.validated_data.get('reason', '')

        try:
            entry1 = ScheduleEntry.objects.get(id=entry1_id)
            entry2 = ScheduleEntry.objects.get(id=entry2_id)
        except ScheduleEntry.DoesNotExist:
            return Response(
                {'error': 'One or both entries not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        with transaction.atomic():
            day1, period1 = entry1.day_of_week, entry1.period
            day2, period2 = entry2.day_of_week, entry2.period

            entry1.day_of_week, entry1.period = day2, period2
            entry2.day_of_week, entry2.period = day1, period1

            entry1.save()
            entry2.save()

            if reason:
                SwapRequest.objects.create(
                    semester=entry1.semester,
                    requesting_teacher=entry1.teacher,
                    target_teacher=entry2.teacher,
                    entry1=entry1,
                    entry2=entry2,
                    reason=reason,
                    status='approved'
                )

        return Response({'status': 'success', 'message': 'Swap completed'})

    @action(detail=False, methods=['post'])
    def substitute(self, request):
        req_serializer = SubstituteRequestSerializer(data=request.data)
        if not req_serializer.is_valid():
            return Response(req_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        entry_id = req_serializer.validated_data['entry_id']
        substitute_teacher_id = req_serializer.validated_data['substitute_teacher_id']
        start_date = req_serializer.validated_data['start_date']
        end_date = req_serializer.validated_data['end_date']
        reason = req_serializer.validated_data['reason']

        try:
            entry = ScheduleEntry.objects.select_related(
                'semester', 'teacher', 'original_teacher', 'course', 'class_id', 'classroom'
            ).get(id=entry_id)
            substitute_teacher = Teacher.objects.get(id=substitute_teacher_id)
        except (ScheduleEntry.DoesNotExist, Teacher.DoesNotExist):
            return Response(
                {'error': 'Entry or teacher not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        original_teacher = entry.scheduled_teacher()
        semester = entry.semester

        if substitute_teacher_id == original_teacher.id:
            return Response(
                {'error': '代课老师不能与原任老师相同。'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if start_date < semester.start_date or end_date > semester.end_date:
            return Response(
                {'error': (
                    f'代课日期必须在学期日期范围内：'
                    f'{semester.start_date:%Y-%m-%d} 至 {semester.end_date:%Y-%m-%d}。'
                )},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not has_matching_weekday(start_date, end_date, entry.day_of_week):
            weekday_names = ['一', '二', '三', '四', '五', '六', '日']
            return Response(
                {'error': (
                    f'{start_date:%Y-%m-%d} 至 {end_date:%Y-%m-%d} '
                    f'内没有周{weekday_names[entry.day_of_week - 1]}的课。'
                )},
                status=status.HTTP_400_BAD_REQUEST
            )

        conflicting_entry, conflict_date = find_substitute_conflict(
            entry, substitute_teacher, start_date, end_date
        )
        if conflicting_entry:
            weekday_names = ['一', '二', '三', '四', '五', '六', '日']
            return Response(
                {'error': (
                    f'{substitute_teacher.name} 在 {conflict_date:%Y-%m-%d}'
                    f'（周{weekday_names[conflict_date.isoweekday() - 1]}）'
                    f'第{entry.period}节已有 '
                    f'{conflicting_entry.class_id.name} 的 '
                    f'{conflicting_entry.course.name}（{conflicting_entry.classroom.name}），'
                    '不能再安排这节代课。'
                )},
                status=status.HTTP_409_CONFLICT
            )

        with transaction.atomic():
            # 同一节课的新一段代课直接顶掉之前的代课段。
            Substitute.objects.filter(affected_entry=entry).delete()

            # 兼容旧接口曾把代课老师写入 entry.teacher 的数据，登记新代课时修复原任课。
            if entry.original_teacher_id and entry.teacher_id != entry.original_teacher_id:
                entry.teacher_id = entry.original_teacher_id
                entry.original_teacher = None
                entry.save(update_fields=['teacher', 'original_teacher', 'updated_at'])
                original_teacher = entry.scheduled_teacher()

            Substitute.objects.create(
                semester=semester,
                original_teacher=original_teacher,
                substitute_teacher=substitute_teacher,
                affected_entry=entry,
                start_date=start_date,
                end_date=end_date,
                reason=reason
            )

        entry.refresh_from_db()
        entry = ScheduleEntry.objects.filter(id=entry.id).prefetch_related(
            Prefetch(
                'substitute_records',
                queryset=Substitute.objects.filter(is_active=True).select_related(
                    'original_teacher', 'substitute_teacher'
                )
            )
        ).first()
        serializer = ScheduleEntryDetailSerializer(
            entry,
            context={'request': request, 'schedule_date': start_date}
        )
        return Response({
            'status': 'success',
            'message': '代课安排已登记，结束日期后课表将自动恢复为原任老师。',
            'entry': serializer.data
        })

    @action(detail=False, methods=['get'])
    def export_pdf(self, request):
        semester_id = request.query_params.get('semester_id')
        entity_type = request.query_params.get('type')
        entity_id = request.query_params.get('id')
        on_date = get_requested_date(request)

        try:
            semester = Semester.objects.get(id=semester_id)
        except Semester.DoesNotExist:
            return Response(
                {'error': 'Semester not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        pdf_buffer = None
        filename = 'timetable.pdf'

        try:
            if entity_type == 'class':
                class_obj = Class.objects.get(id=entity_id)
                pdf_buffer = generate_class_timetable_pdf(
                    class_obj, semester, on_date
                )
                filename = f'{class_obj.name}_课表.pdf'
            elif entity_type == 'teacher':
                teacher = Teacher.objects.get(id=entity_id)
                pdf_buffer = generate_teacher_timetable_pdf(
                    teacher, semester, on_date
                )
                filename = f'{teacher.name}_课表.pdf'
            elif entity_type == 'classroom':
                classroom = Classroom.objects.get(id=entity_id)
                pdf_buffer = generate_classroom_timetable_pdf(
                    classroom, semester, on_date
                )
                filename = f'{classroom.name}_课表.pdf'
            else:
                return Response(
                    {'error': 'Invalid type. Must be class, teacher, or classroom'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except (Class.DoesNotExist, Teacher.DoesNotExist, Classroom.DoesNotExist):
            return Response(
                {'error': 'Entity not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        response = HttpResponse(pdf_buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class ConflictViewSet(viewsets.ModelViewSet):
    queryset = Conflict.objects.all().select_related('semester')
    serializer_class = ConflictSerializer
    permission_classes = [AllowAny]


class SwapRequestViewSet(viewsets.ModelViewSet):
    queryset = SwapRequest.objects.all().select_related(
        'semester', 'requesting_teacher', 'target_teacher'
    )
    serializer_class = SwapRequestSerializer
    permission_classes = [AllowAny]


class SubstituteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Substitute.objects.filter(is_active=True).select_related(
        'semester', 'original_teacher', 'substitute_teacher',
        'affected_entry', 'affected_entry__course', 'affected_entry__class_id'
    )
    serializer_class = SubstituteSerializer
    permission_classes = [AllowAny]
