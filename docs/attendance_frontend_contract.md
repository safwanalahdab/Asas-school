# عقد واجهة الحضور

جميع الاستجابات تتبع الغلاف العام للمشروع: `success`, `code`, `message`, `data`, `meta`.

## الأدوار

- المعلّم: يعرض كشوف الشعب التي كان مكلّفًا بها في تاريخ الكشف، وينشئ كشف اليوم مرة واحدة فقط. لا يعدّل السجلات بعد الحفظ.
- الموجّه وإدارة المدرسة: عرض وإنشاء وتصحيح السجلات، والتعديل الجماعي، والمغادرة الطبيعية.
- مدير النظام: كامل الصلاحيات. الأمانة وولي الأمر والدعم التقني ممنوعون.

## المسارات

| Method | URL | الصلاحية | الطلب |
|---|---|---|---|
| GET | `/api/v1/attendance/sheets/` | Teacher/Supervisor/Admin | فلاتر اختيارية |
| GET | `/api/v1/attendance/sheets/{id}/` | حسب نطاق الدور | — |
| POST | `/api/v1/attendance/sheets/` | Teacher/Supervisor/Admin | `section`, `records` |
| POST | `/api/v1/attendance/sheets/{id}/bulk-update/` | Supervisor/Admin | `records` |
| POST | `/api/v1/attendance/sheets/{id}/normal-departure/` | Supervisor/Admin | `departure_time`, `departure_method` |
| GET | `/api/v1/attendance/records/` | Teacher/Supervisor/Admin | فلاتر اختيارية |
| GET | `/api/v1/attendance/records/{id}/` | حسب نطاق الدور | — |
| PATCH | `/api/v1/attendance/records/{id}/` | Supervisor/Admin | حقول الحضور فقط |

إنشاء الكشف لا يقبل تاريخًا؛ الخادم يستخدم تاريخ دمشق الحالي. يجب إرسال جميع تسجيلات الطلاب الفعالين في الشعبة، ولا يقبل `unmarked`.

## القيم

- `status`: `unmarked` غير محدد، `present` حاضر، `absent` غائب.
- `absence_type`: `excused` بعذر، `unexcused` دون عذر.
- `absence_reason_source`: `guardian` ولي الأمر، `school` إدارة المدرسة.
- وسائل النقل: `school_bus` باص المدرسة، `guardian` ولي الأمر.

## سلوك الواجهة

للمعلّم: عند عدم وجود كشف يظهر زر «أخذ الحضور»، وبعد وجوده يصبح العرض فقط. للموجّه والإدارة تظهر أدوات التصحيح والتعديل الجماعي والمغادرة الطبيعية. لا يظهر زر أخذ الحضور يومي الجمعة والسبت.

## أخطاء مهمة

| code | HTTP | المعنى |
|---|---:|---|
| `ATTENDANCE_SHEET_ALREADY_EXISTS` | 400 | يوجد كشف للشعبة واليوم |
| `ATTENDANCE_NOT_ALLOWED_ON_WEEKEND` | 400 | الجمعة أو السبت |
| `ATTENDANCE_TEACHER_NOT_ASSIGNED` | 403 | المعلم غير مكلّف بالشعبة |
| `ATTENDANCE_INVALID_ROSTER` | 400 | القائمة ناقصة أو زائدة أو مكررة |
| `ATTENDANCE_EMPTY_ROSTER` | 400 | لا طلاب فعالين |
| `ATTENDANCE_RECORD_INVALID` | 400 | بيانات الحالة متناقضة |
| `ATTENDANCE_ACCESS_DENIED` | 403 | الدور غير مسموح |
