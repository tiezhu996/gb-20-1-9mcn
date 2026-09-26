from io import BytesIO

from django.db.models import Prefetch, Q
from django.utils import timezone
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from .models import ScheduleEntry, Substitute


def _get_days(semester):
    days = ['星期一', '星期二', '星期三', '星期四', '星期五']
    if semester.weekly_days >= 6:
        days.append('星期六')
    if semester.weekly_days >= 7:
        days.append('星期日')
    return days


def _get_periods(semester):
    periods = []
    for index, p in enumerate(semester.daily_periods):
        periods.append(p.get('name') or f"第{p.get('order', index + 1)}节")
    if not periods:
        periods = [f'第{i + 1}节' for i in range(7)]
    return periods


def _entries_with_substitutes(semester):
    return ScheduleEntry.objects.filter(semester=semester).select_related(
        'course', 'teacher', 'original_teacher', 'classroom', 'class_id'
    ).prefetch_related(
        Prefetch(
            'substitute_records',
            queryset=Substitute.objects.filter(is_active=True).select_related(
                'original_teacher', 'substitute_teacher'
            )
        )
    )


def _teacher_related_entries(semester, teacher, on_date):
    active_substitute = Q(
        substitute_records__is_active=True,
        substitute_records__substitute_teacher=teacher,
        substitute_records__start_date__lte=on_date,
        substitute_records__end_date__gte=on_date
    )
    return _entries_with_substitutes(semester).filter(
        Q(teacher=teacher) | Q(original_teacher=teacher) | active_substitute
    ).distinct()


def _teacher_lines(entry, on_date):
    original_teacher = entry.scheduled_teacher()
    effective_teacher = entry.effective_teacher(on_date)
    if effective_teacher == original_teacher:
        return [f'教师：{effective_teacher.name}']
    return [
        f'实际上课：{effective_teacher.name}',
        f'原任教师：{original_teacher.name}',
    ]


def _base_document(buffer):
    return SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=1 * cm,
        bottomMargin=1 * cm
    )


def _build_pdf(buffer, title, semester, entries, content_builder, colors_config=None):
    colors_config = colors_config or {
        'header': '#1976D2',
        'row': '#E3F2FD',
        'grid': '#90CAF9',
    }
    doc = _base_document(buffer)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=18,
        spaceAfter=20,
        alignment=TA_CENTER
    )

    story = [Paragraph(title, title_style), Spacer(1, 0.5 * cm)]
    days = _get_days(semester)
    periods = _get_periods(semester)

    schedule_grid = [[''] + days]
    for period_name in periods:
        schedule_grid.append([period_name] + [''] * len(days))

    for entry in entries:
        try:
            row_idx = entry.period
            col_idx = entry.day_of_week
            if 1 <= row_idx <= len(periods) and 1 <= col_idx <= len(days):
                schedule_grid[row_idx][col_idx] = content_builder(entry)
        except IndexError:
            continue

    col_widths = [2 * cm] + [(doc.width / len(days))] * len(days)
    row_heights = [1 * cm] + [1.8 * cm] * len(periods)
    table = Table(schedule_grid, colWidths=col_widths, rowHeights=row_heights)
    table.setStyle(_table_style(colors_config))
    story.append(table)
    doc.build(story)
    buffer.seek(0)
    return buffer


def _table_style(colors_config):
    return TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(colors_config['header'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor(colors_config['row'])),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor(colors_config['grid'])),
    ])


def generate_class_timetable_pdf(class_obj, semester, on_date=None):
    if on_date is None:
        on_date = timezone.localdate()
    buffer = BytesIO()
    entries = _entries_with_substitutes(semester).filter(class_id=class_obj)

    def build_content(entry):
        return '\n'.join([
            entry.course.name,
            *_teacher_lines(entry, on_date),
            entry.classroom.name,
        ])

    return _build_pdf(
        buffer,
        f'班级课表 - {class_obj.name} ({semester.name})',
        semester,
        entries,
        build_content,
        {'header': '#1976D2', 'row': '#E3F2FD', 'grid': '#90CAF9'}
    )


def generate_teacher_timetable_pdf(teacher, semester, on_date=None):
    if on_date is None:
        on_date = timezone.localdate()
    buffer = BytesIO()
    entries = _teacher_related_entries(semester, teacher, on_date)

    def build_content(entry):
        return '\n'.join([
            entry.course.name,
            entry.class_id.name,
            entry.classroom.name,
            *_teacher_lines(entry, on_date),
        ])

    return _build_pdf(
        buffer,
        f'教师课表 - {teacher.name} ({semester.name})',
        semester,
        entries,
        build_content,
        {'header': '#388E3C', 'row': '#E8F5E9', 'grid': '#A5D6A7'}
    )


def generate_classroom_timetable_pdf(classroom, semester, on_date=None):
    if on_date is None:
        on_date = timezone.localdate()
    buffer = BytesIO()
    entries = _entries_with_substitutes(semester).filter(classroom=classroom)

    def build_content(entry):
        return '\n'.join([
            entry.course.name,
            entry.class_id.name,
            *_teacher_lines(entry, on_date),
        ])

    return _build_pdf(
        buffer,
        f'教室课表 - {classroom.name} ({semester.name})',
        semester,
        entries,
        build_content,
        {'header': '#E64A19', 'row': '#FBE9E7', 'grid': '#FFAB91'}
    )
