import { Component, OnInit, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatInputModule } from '@angular/material/input';
import { ApiService } from '../../services/api.service';
import type {
  ScheduleEntry, Semester, Class, Teacher, Classroom
} from '../../types';

@Component({
  selector: 'app-timetable',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatSelectModule,
    MatButtonModule,
    MatCheckboxModule,
    MatCardModule,
    MatTableModule,
    MatIconModule,
    MatChipsModule,
    MatInputModule
  ],
  template: `
    <div class="page-container">
      <h1 class="page-title">课表管理</h1>

      <div class="filter-bar">
        <mat-form-field class="filter-select">
          <mat-label>学期</mat-label>
          <mat-select [(value)]="selectedSemesterId" (selectionChange)="onSemesterChange()">
            <mat-option *ngFor="let s of semesters" [value]="s.id">
              {{ s.name }}
              <span *ngIf="s.is_active" style="color: green;"> (当前)</span>
            </mat-option>
          </mat-select>
        </mat-form-field>

        <mat-form-field class="filter-select">
          <mat-label>课表日期</mat-label>
          <input matInput type="date" [(ngModel)]="selectedDate" (change)="loadSchedules()">
        </mat-form-field>

        <mat-form-field class="filter-select">
          <mat-label>查看方式</mat-label>
          <mat-select [(value)]="viewMode" (selectionChange)="loadSchedules()">
            <mat-option value="class">按班级</mat-option>
            <mat-option value="teacher">按教师</mat-option>
            <mat-option value="classroom">按教室</mat-option>
          </mat-select>
        </mat-form-field>

        <mat-form-field class="filter-select" *ngIf="viewMode === 'class'">
          <mat-label>班级</mat-label>
          <mat-select [(value)]="selectedClassId" (selectionChange)="loadSchedules()">
            <mat-option *ngFor="let c of classes" [value]="c.id">
              {{ c.grade }}年级 {{ c.name }}
            </mat-option>
          </mat-select>
        </mat-form-field>

        <mat-form-field class="filter-select" *ngIf="viewMode === 'teacher'">
          <mat-label>教师</mat-label>
          <mat-select [(value)]="selectedTeacherId" (selectionChange)="loadSchedules()">
            <mat-option *ngFor="let t of teachers" [value]="t.id">
              {{ t.name }}
            </mat-option>
          </mat-select>
        </mat-form-field>

        <mat-form-field class="filter-select" *ngIf="viewMode === 'classroom'">
          <mat-label>教室</mat-label>
          <mat-select [(value)]="selectedClassroomId" (selectionChange)="loadSchedules()">
            <mat-option *ngFor="let c of classrooms" [value]="c.id">
              {{ c.name }}
            </mat-option>
          </mat-select>
        </mat-form-field>
      </div>

      <div class="action-bar">
        <button mat-raised-button color="primary" (click)="runAutoSchedule()" [disabled]="!selectedSemesterId">
          <mat-icon>auto_awesome</mat-icon>
          自动排课
        </button>
        <button mat-raised-button (click)="runAutoSchedule(false)" [disabled]="!selectedSemesterId">
          <mat-icon>refresh</mat-icon>
          重新排课（忽略锁定）
        </button>
        <button mat-button (click)="loadSchedules()">
          <mat-icon>refresh</mat-icon>
          刷新
        </button>
        <button mat-raised-button color="accent" (click)="exportPdf()" [disabled]="!canExport">
          <mat-icon>picture_as_pdf</mat-icon>
          导出 PDF
        </button>
        <button mat-raised-button (click)="exportImage()" [disabled]="!canExport">
          <mat-icon>image</mat-icon>
          导出图片
        </button>
      </div>

      <mat-card *ngIf="showSubstituteForm && selectedEntry" class="substitute-form">
        <mat-card-header>
          <mat-icon color="primary">person_add</mat-icon>
          <mat-card-title>登记代课</mat-card-title>
          <mat-card-subtitle>
            {{ selectedEntry.class_name }} · {{ selectedEntry.course_name }} ·
            周{{ weekdayName(selectedEntry.day_of_week) }}第{{ selectedEntry.period }}节 ·
            原任教师：{{ selectedEntry.scheduled_teacher_name || selectedEntry.original_teacher_name }}
          </mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <div class="substitute-fields">
            <mat-form-field>
              <mat-label>代课老师</mat-label>
              <mat-select [(ngModel)]="substituteTeacherId">
                <mat-option
                  *ngFor="let t of availableSubstituteTeachers()"
                  [value]="t.id"
                >
                  {{ t.name }}（{{ t.subject }}）
                </mat-option>
              </mat-select>
            </mat-form-field>

            <mat-form-field>
              <mat-label>开始日期</mat-label>
              <input matInput type="date" [(ngModel)]="substituteStartDate">
            </mat-form-field>

            <mat-form-field>
              <mat-label>结束日期</mat-label>
              <input matInput type="date" [(ngModel)]="substituteEndDate">
            </mat-form-field>

            <mat-form-field class="substitute-reason">
              <mat-label>请假/代课原因</mat-label>
              <input matInput [(ngModel)]="substituteReason" placeholder="如：教师临时外出培训">
            </mat-form-field>
          </div>

          <p *ngIf="substituteError" class="substitute-error">{{ substituteError }}</p>

          <div class="substitute-actions">
            <button
              mat-raised-button
              color="primary"
              (click)="saveSubstitute()"
              [disabled]="submittingSubstitute"
            >
              保存代课
            </button>
            <button mat-button (click)="cancelSubstitute()" [disabled]="submittingSubstitute">取消</button>
          </div>
        </mat-card-content>
      </mat-card>

      <div class="timetable-container" #timetableContainer>
        <div *ngIf="schedules.length > 0">
          <h3 style="padding: 16px 16px 0; margin: 0;">{{ currentViewTitle }}</h3>

          <div style="padding: 16px; overflow-x: auto;">
            <table class="mat-elevation-z2" style="width: 100%; border-collapse: collapse;">
              <thead>
                <tr style="background: #1976d2; color: white;">
                  <th style="padding: 12px; text-align: center; min-width: 100px;">节次</th>
                  <th *ngFor="let day of displayedWeekDays" [attr.aria-label]="weekdayName(day)" style="padding: 12px; text-align: center; min-width: 150px;">
                    {{ weekdayName(day) }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let period of periods; let i = index" [style.background]="i % 2 === 0 ? '#f9f9f9' : 'white'">
                  <td style="padding: 12px; text-align: center; font-weight: bold; border: 1px solid #ddd;">
                    {{ period.name }}
                  </td>
                  <td
                    *ngFor="let day of displayedWeekDays"
                    style="padding: 8px; border: 1px solid #ddd; vertical-align: top; min-height: 80px;"
                  >
                    <ng-container *ngFor="let entry of getEntryAt(day, i + 1)">
                      <mat-card
                        class="schedule-card"
                        [class.conflict-entry]="entry.is_conflict"
                        [class.locked-entry]="entry.is_locked"
                        [class.substitute-entry]="entry.has_active_substitute"
                        style="margin-bottom: 4px;"
                      >
                        <div class="schedule-course">{{ entry.course_name }}</div>
                        <div class="schedule-detail">
                          实际：{{ entry.effective_teacher_name || entry.teacher_name }}
                        </div>
                        <div class="schedule-detail" *ngIf="entry.has_active_substitute">
                          原任：{{ entry.scheduled_teacher_name || entry.original_teacher_name }}
                        </div>
                        <div class="schedule-detail" *ngIf="entry.has_active_substitute">
                          代课：{{ entry.substitute_start_date }} 至 {{ entry.substitute_end_date }}
                        </div>
                        <div class="schedule-detail">{{ entry.classroom_name }}</div>
                        <div class="schedule-detail">{{ entry.class_name }}</div>
                        <div style="margin-top: 4px; display: flex; gap: 4px; flex-wrap: wrap;">
                          <mat-chip *ngIf="entry.is_locked" color="accent" selected>锁定</mat-chip>
                          <mat-chip *ngIf="entry.is_conflict" color="warn" selected>冲突</mat-chip>
                          <mat-chip *ngIf="entry.has_active_substitute" color="primary" selected>代课中</mat-chip>
                          <button
                            mat-icon-button
                            size="small"
                            color="primary"
                            (click)="startSubstitute(entry)"
                            title="登记/替换代课"
                          >
                            <mat-icon>person_add</mat-icon>
                          </button>
                          <button
                            mat-icon-button
                            size="small"
                            (click)="toggleLock(entry)"
                            [title]="entry.is_locked ? '解锁' : '锁定'"
                          >
                            <mat-icon>{{ entry.is_locked ? 'lock' : 'lock_open' }}</mat-icon>
                          </button>
                        </div>
                      </mat-card>
                    </ng-container>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div *ngIf="schedules.length === 0 && selectedSemesterId" style="padding: 40px; text-align: center;">
          <p>当前没有排课数据。点击"自动排课"按钮开始。</p>
        </div>

        <div *ngIf="!selectedSemesterId" style="padding: 40px; text-align: center;">
          <p>请先选择一个学期。</p>
        </div>
      </div>

      <div *ngIf="schedulingMessage" style="margin-top: 16px;">
        <mat-card>
          <mat-card-content>
            <p>{{ schedulingMessage }}</p>
          </mat-card-content>
        </mat-card>
      </div>
    </div>
  `
})
export class TimetableComponent implements OnInit {
  @ViewChild('timetableContainer') timetableContainer!: ElementRef;

  semesters: Semester[] = [];
  classes: Class[] = [];
  teachers: Teacher[] = [];
  classrooms: Classroom[] = [];
  schedules: ScheduleEntry[] = [];
  selectedSemesterId: number | null = null;
  selectedClassId: number | null = null;
  selectedTeacherId: number | null = null;
  selectedClassroomId: number | null = null;
  selectedDate = TimetableComponent.formatLocalDate(new Date());
  viewMode: 'class' | 'teacher' | 'classroom' = 'class';
  schedulingMessage: string = '';
  currentSemester: Semester | null = null;

  showSubstituteForm = false;
  selectedEntry: ScheduleEntry | null = null;
  substituteTeacherId: number | null = null;
  substituteStartDate = this.selectedDate;
  substituteEndDate = this.selectedDate;
  substituteReason = '';
  substituteError = '';
  submittingSubstitute = false;

  weekDays = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日'];
  displayedWeekDays = [1, 2, 3, 4, 5];
  periods = [
    { name: '第1节', order: 1 },
    { name: '第2节', order: 2 },
    { name: '第3节', order: 3 },
    { name: '第4节', order: 4 },
    { name: '第5节', order: 5 },
    { name: '第6节', order: 6 },
    { name: '第7节', order: 7 },
  ];

  get canExport(): boolean {
    if (!this.selectedSemesterId) return false;
    if (this.viewMode === 'class') return !!this.selectedClassId;
    if (this.viewMode === 'teacher') return !!this.selectedTeacherId;
    if (this.viewMode === 'classroom') return !!this.selectedClassroomId;
    return false;
  }

  get currentViewTitle(): string {
    if (this.viewMode === 'class') {
      const cls = this.classes.find(c => c.id === this.selectedClassId);
      return cls ? `${cls.grade}年级 ${cls.name} 课表（${this.selectedDate}）` : '';
    }
    if (this.viewMode === 'teacher') {
      const t = this.teachers.find(t => t.id === this.selectedTeacherId);
      return t ? `${t.name} 教师课表（${this.selectedDate}）` : '';
    }
    if (this.viewMode === 'classroom') {
      const c = this.classrooms.find(c => c.id === this.selectedClassroomId);
      return c ? `${c.name} 教室课表（${this.selectedDate}）` : '';
    }
    return '';
  }

  constructor(private api: ApiService) {}

  private static formatLocalDate(date: Date): string {
    const year = date.getFullYear();
    const month = `${date.getMonth() + 1}`.padStart(2, '0');
    const day = `${date.getDate()}`.padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  ngOnInit(): void {
    this.loadSemesters();
    this.loadClasses();
    this.loadTeachers();
    this.loadClassrooms();
  }

  loadSemesters(): void {
    this.api.getSemesters().subscribe(data => {
      this.semesters = data;
      const active = data.find(s => s.is_active);
      if (active) {
        this.selectedSemesterId = active.id;
        this.currentSemester = active;
        this.updatePeriodsFromSemester();
        this.loadSchedules();
      }
    });
  }

  loadClasses(): void {
    this.api.getClasses().subscribe(data => {
      this.classes = data;
      if (data.length > 0 && !this.selectedClassId) {
        this.selectedClassId = data[0].id;
        if (this.selectedSemesterId) this.loadSchedules();
      }
    });
  }

  loadTeachers(): void {
    this.api.getTeachers().subscribe(data => {
      this.teachers = data;
      if (data.length > 0 && !this.selectedTeacherId) {
        this.selectedTeacherId = data[0].id;
      }
    });
  }

  loadClassrooms(): void {
    this.api.getClassrooms().subscribe(data => {
      this.classrooms = data;
      if (data.length > 0 && !this.selectedClassroomId) {
        this.selectedClassroomId = data[0].id;
      }
    });
  }

  updatePeriodsFromSemester(): void {
    if (this.currentSemester?.daily_periods?.length) {
      this.periods = this.currentSemester.daily_periods
        .slice()
        .sort((a, b) => a.order - b.order);
    }
    this.displayedWeekDays = Array.from(
      { length: this.currentSemester?.weekly_days || 5 },
      (_, index) => index + 1
    );
  }

  onSemesterChange(): void {
    if (this.selectedSemesterId) {
      this.currentSemester = this.semesters.find(s => s.id === this.selectedSemesterId) || null;
      this.updatePeriodsFromSemester();
      this.loadSchedules();
    }
  }

  loadSchedules(): void {
    if (!this.selectedSemesterId) return;

    let obs;
    if (this.viewMode === 'class' && this.selectedClassId) {
      obs = this.api.getSchedulesByClass(this.selectedSemesterId, this.selectedClassId, this.selectedDate);
    } else if (this.viewMode === 'teacher' && this.selectedTeacherId) {
      obs = this.api.getSchedulesByTeacher(this.selectedSemesterId, this.selectedTeacherId, this.selectedDate);
    } else if (this.viewMode === 'classroom' && this.selectedClassroomId) {
      obs = this.api.getSchedulesByClassroom(this.selectedSemesterId, this.selectedClassroomId, this.selectedDate);
    } else {
      obs = this.api.getSchedulesBySemester(this.selectedSemesterId, this.selectedDate);
    }

    obs.subscribe(data => {
      this.schedules = data;
    });
  }

  getEntryAt(day: number, period: number): ScheduleEntry[] {
    return this.schedules.filter(e => e.day_of_week === day && e.period === period);
  }

  weekdayName(day: number): string {
    return this.weekDays[day - 1] || `星期${day}`;
  }

  availableSubstituteTeachers(): Teacher[] {
    const originalTeacherId = this.selectedEntry?.scheduled_teacher ?? this.selectedEntry?.original_teacher;
    return this.teachers.filter(teacher => teacher.is_active && teacher.id !== originalTeacherId);
  }

  startSubstitute(entry: ScheduleEntry): void {
    this.selectedEntry = entry;
    this.showSubstituteForm = true;
    this.substituteError = '';
    this.substituteReason = '';
    this.substituteTeacherId = this.availableSubstituteTeachers()[0]?.id ?? null;
    this.substituteStartDate = this.selectedDate;
    this.substituteEndDate = this.selectedDate;
  }

  cancelSubstitute(): void {
    this.showSubstituteForm = false;
    this.selectedEntry = null;
    this.substituteError = '';
    this.submittingSubstitute = false;
  }

  saveSubstitute(): void {
    if (!this.selectedEntry) return;

    if (!this.substituteTeacherId) {
      this.substituteError = '请选择代课老师。';
      return;
    }
    if (!this.substituteStartDate || !this.substituteEndDate) {
      this.substituteError = '请选择代课开始日期和结束日期。';
      return;
    }
    if (this.substituteEndDate < this.substituteStartDate) {
      this.substituteError = '结束日期不能早于开始日期。';
      return;
    }
    if (!this.substituteReason.trim()) {
      this.substituteError = '请填写请假/代课原因。';
      return;
    }

    this.submittingSubstitute = true;
    this.substituteError = '';
    this.api.assignSubstitute(
      this.selectedEntry.id,
      this.substituteTeacherId,
      this.substituteStartDate,
      this.substituteEndDate,
      this.substituteReason.trim()
    ).subscribe({
      next: () => {
        this.schedulingMessage = '代课已登记；结束日期后课表会自动恢复为原任老师。';
        this.cancelSubstitute();
        this.loadSchedules();
      },
      error: (error: HttpErrorResponse) => {
        this.submittingSubstitute = false;
        this.substituteError = error.error?.error || '代课登记失败，请检查输入后重试。';
      }
    });
  }

  runAutoSchedule(respectLocked = true): void {
    if (!this.selectedSemesterId) return;
    this.schedulingMessage = '正在自动排课，请稍候...';

    this.api.autoSchedule(this.selectedSemesterId, respectLocked).subscribe(result => {
      const total = result.total_entries || 0;
      const conflicts = (result.conflicts || []).length;
      const messages = result.scheduling_messages || [];

      let msg = `排课完成！共安排 ${total} 节课`;
      if (conflicts > 0) {
        msg += `，发现 ${conflicts} 个冲突`;
      }
      if (messages.length > 0) {
        msg += `。提示: ${messages.map((m: any) => m.message).join('; ')}`;
      }
      this.schedulingMessage = msg;
      this.loadSchedules();
    });
  }

  toggleLock(entry: ScheduleEntry): void {
    this.api.updateScheduleEntry(entry.id, { is_locked: !entry.is_locked }).subscribe(() => {
      entry.is_locked = !entry.is_locked;
    });
  }

  exportPdf(): void {
    if (!this.selectedSemesterId) return;
    let type: 'class' | 'teacher' | 'classroom' = 'class';
    let id = 0;

    if (this.viewMode === 'class' && this.selectedClassId) {
      type = 'class';
      id = this.selectedClassId;
    } else if (this.viewMode === 'teacher' && this.selectedTeacherId) {
      type = 'teacher';
      id = this.selectedTeacherId;
    } else if (this.viewMode === 'classroom' && this.selectedClassroomId) {
      type = 'classroom';
      id = this.selectedClassroomId;
    } else {
      return;
    }

    this.api.exportPdf(this.selectedSemesterId, type, id, this.selectedDate).subscribe(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'timetable.pdf';
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  async exportImage(): Promise<void> {
    try {
      const html2canvas = (await import('html2canvas')).default;
      const element = this.timetableContainer.nativeElement;
      const canvas = await html2canvas(element, {
        backgroundColor: '#ffffff',
        scale: 2
      });
      const link = document.createElement('a');
      link.download = 'timetable.png';
      link.href = canvas.toDataURL();
      link.click();
    } catch (e) {
      alert('图片导出功能需要 html2canvas 库');
      console.error(e);
    }
  }
}
