from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Classroom, Class, Course, Semester, Teacher
from .models import ScheduleEntry, Substitute


class SubstituteAPITestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.semester = Semester.objects.create(
            name='测试学期',
            start_date=date(2026, 9, 1),
            end_date=date(2026, 11, 30),
            is_active=True,
            daily_periods=[{'name': f'第{i}节', 'order': i} for i in range(1, 8)],
            weekly_days=5,
            holidays=[]
        )
        self.original_teacher = Teacher.objects.create(name='张老师', subject='数学')
        self.substitute_teacher = Teacher.objects.create(name='李老师', subject='数学')
        self.busy_teacher = Teacher.objects.create(name='王老师', subject='物理')
        self.classroom = Classroom.objects.create(name='101', capacity=40)
        self.other_classroom = Classroom.objects.create(name='102', capacity=40)
        self.class_one = Class.objects.create(grade=10, name='1班', student_count=40)
        self.class_two = Class.objects.create(grade=10, name='2班', student_count=40)
        self.course = Course.objects.create(name='数学', weekly_hours=1)
        self.other_course = Course.objects.create(name='物理', weekly_hours=1)

        self.entry = ScheduleEntry.objects.create(
            semester=self.semester,
            class_id=self.class_one,
            course=self.course,
            teacher=self.original_teacher,
            classroom=self.classroom,
            day_of_week=5,
            period=1
        )
        # 2026-09-25 是周五。
        self.within_date = date(2026, 9, 25)
        self.start_date = date(2026, 9, 25)
        self.end_date = date(2026, 10, 2)
        self.after_date = date(2026, 10, 9)

    def substitute_payload(self, **overrides):
        payload = {
            'entry_id': self.entry.id,
            'substitute_teacher_id': self.substitute_teacher.id,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'reason': '临时请假'
        }
        payload.update(overrides)
        return payload

    def test_substitute_shows_effective_and_original_teacher_only_within_period(self):
        response = self.client.post(
            '/api/schedules/substitute/',
            self.substitute_payload(),
            format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.teacher, self.original_teacher)

        within = self.client.get(
            f'/api/schedules/by_class/?semester_id={self.semester.id}'
            f'&class_id={self.class_one.id}&date={self.within_date.isoformat()}'
        ).json()
        self.assertEqual(within[0]['effective_teacher'], self.substitute_teacher.id)
        self.assertEqual(within[0]['scheduled_teacher'], self.original_teacher.id)
        self.assertTrue(within[0]['has_active_substitute'])

        after = self.client.get(
            f'/api/schedules/by_class/?semester_id={self.semester.id}'
            f'&class_id={self.class_one.id}&date={self.after_date.isoformat()}'
        ).json()
        self.assertEqual(after[0]['effective_teacher'], self.original_teacher.id)
        self.assertEqual(after[0]['scheduled_teacher'], self.original_teacher.id)
        self.assertFalse(after[0]['has_active_substitute'])

    def test_original_teacher_schedule_keeps_entry_during_substitute_period(self):
        self.client.post('/api/schedules/substitute/', self.substitute_payload(), format='json')

        response = self.client.get(
            f'/api/schedules/by_teacher/?semester_id={self.semester.id}'
            f'&teacher_id={self.original_teacher.id}'
            f'&date={self.within_date.isoformat()}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]['id'], self.entry.id)

    def test_substitute_teacher_schedule_includes_entry_within_period_only(self):
        self.client.post('/api/schedules/substitute/', self.substitute_payload(), format='json')

        within = self.client.get(
            f'/api/schedules/by_teacher/?semester_id={self.semester.id}'
            f'&teacher_id={self.substitute_teacher.id}'
            f'&date={self.within_date.isoformat()}'
        )
        self.assertEqual(len(within.json()), 1)
        self.assertEqual(within.json()[0]['effective_teacher'], self.substitute_teacher.id)

        after = self.client.get(
            f'/api/schedules/by_teacher/?semester_id={self.semester.id}'
            f'&teacher_id={self.substitute_teacher.id}'
            f'&date={self.after_date.isoformat()}'
        )
        self.assertEqual(len(after.json()), 0)

    def test_new_substitute_segment_replaces_previous_active_segment(self):
        self.client.post('/api/schedules/substitute/', self.substitute_payload(), format='json')
        replacement_end = date(2026, 9, 30)

        response = self.client.post(
            '/api/schedules/substitute/',
            self.substitute_payload(end_date=replacement_end.isoformat()),
            format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Substitute.objects.filter(is_active=True).count(), 1)
        active = Substitute.objects.get(is_active=True)
        self.assertEqual(active.end_date, replacement_end)
        self.assertEqual(Substitute.objects.count(), 1)

        after_old_range = self.client.get(
            f'/api/schedules/by_class/?semester_id={self.semester.id}'
            f'&class_id={self.class_one.id}&date=2026-10-02'
        ).json()
        self.assertFalse(after_old_range[0]['has_active_substitute'])

    def test_registration_is_rejected_when_substitute_has_another_class_at_same_slot(self):
        other_entry = ScheduleEntry.objects.create(
            semester=self.semester,
            class_id=self.class_two,
            course=self.other_course,
            teacher=self.busy_teacher,
            classroom=self.other_classroom,
            day_of_week=5,
            period=1
        )

        response = self.client.post(
            '/api/schedules/substitute/',
            self.substitute_payload(substitute_teacher_id=self.busy_teacher.id),
            format='json'
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn('王老师', response.data['error'])
        self.assertIn(str(other_entry.period), response.data['error'])
        self.assertIn(self.class_two.name, response.data['error'])
        self.assertIn(self.other_course.name, response.data['error'])
        self.assertFalse(Substitute.objects.exists())

    def test_registration_is_rejected_when_other_substitution_shares_a_weekday(self):
        other_entry = ScheduleEntry.objects.create(
            semester=self.semester,
            class_id=self.class_two,
            course=self.other_course,
            teacher=self.busy_teacher,
            classroom=self.other_classroom,
            day_of_week=5,
            period=1
        )
        Substitute.objects.create(
            semester=self.semester,
            original_teacher=self.busy_teacher,
            substitute_teacher=self.substitute_teacher,
            affected_entry=other_entry,
            start_date=date(2026, 9, 18),
            end_date=date(2026, 9, 25),
            reason='上一段重叠代课'
        )

        response = self.client.post('/api/schedules/substitute/', self.substitute_payload(), format='json')
        self.assertEqual(response.status_code, 409)
        self.assertIn('2026-09-25', response.data['error'])

    def test_later_non_overlapping_substitution_period_is_allowed(self):
        other_entry = ScheduleEntry.objects.create(
            semester=self.semester,
            class_id=self.class_two,
            course=self.other_course,
            teacher=self.busy_teacher,
            classroom=self.other_classroom,
            day_of_week=5,
            period=1
        )
        Substitute.objects.create(
            semester=self.semester,
            original_teacher=self.busy_teacher,
            substitute_teacher=self.substitute_teacher,
            affected_entry=other_entry,
            start_date=self.end_date + timedelta(days=7),
            end_date=self.end_date + timedelta(days=14),
            reason='之后的另一段代课'
        )

        response = self.client.post('/api/schedules/substitute/', self.substitute_payload(), format='json')
        self.assertEqual(response.status_code, 200)

    def test_date_range_without_weekday_is_rejected(self):
        # 2026-09-26 是周六，2026-09-27 是周日，不包含该课的周五。
        response = self.client.post(
            '/api/schedules/substitute/',
            self.substitute_payload(
                start_date='2026-09-26',
                end_date='2026-09-27'
            ),
            format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('没有周五', response.data['error'])

    def test_adjacent_substitution_periods_without_shared_weekday_are_allowed(self):
        other_entry = ScheduleEntry.objects.create(
            semester=self.semester,
            class_id=self.class_two,
            course=self.other_course,
            teacher=self.original_teacher,
            classroom=self.other_classroom,
            day_of_week=5,
            period=1
        )
        # 第一段覆盖 10 月 2 日之后的周五，与目标段 10 月 2 日相连但日期不重叠。
        Substitute.objects.create(
            semester=self.semester,
            original_teacher=self.original_teacher,
            substitute_teacher=self.substitute_teacher,
            affected_entry=other_entry,
            start_date=date(2026, 10, 9),
            end_date=date(2026, 10, 16),
            reason='另一段代课'
        )

        response = self.client.post('/api/schedules/substitute/', self.substitute_payload(), format='json')
        self.assertEqual(response.status_code, 200)

    def test_legacy_mutated_substitute_data_is_repaired_when_new_segment_registered(self):
        legacy_substitute = self.substitute_teacher
        self.entry.teacher = legacy_substitute
        self.entry.original_teacher = self.original_teacher
        self.entry.save()

        new_teacher = Teacher.objects.create(name='赵老师', subject='数学')
        response = self.client.post(
            '/api/schedules/substitute/',
            self.substitute_payload(substitute_teacher_id=new_teacher.id),
            format='json'
        )

        self.assertEqual(response.status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.teacher, self.original_teacher)
        self.assertIsNone(self.entry.original_teacher)

    def test_self_substitute_is_rejected(self):
        response = self.client.post(
            '/api/schedules/substitute/',
            self.substitute_payload(substitute_teacher_id=self.original_teacher.id),
            format='json'
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('不能与原任老师相同', response.data['error'])
