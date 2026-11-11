"""
إصلاح تواريخ مخزّنة بصيغة غير موحّدة في SQLite (مثل '2026-8-9' بدل '2026-08-09').

SQLite يخزّن التواريخ كنص، فالتواريخ غير المبطّنة بالأصفار كانت تُرتَّب وتُفلتَر بشكل خاطئ
(مثلاً '2026-8-9' > '2026-10-01' نصياً)، فيظهر سجل الحضور بترتيب زمني غير صحيح
وتُحسب الإحصائيات ضمن الفترات بشكل ناقص. هذه الهجرة توحّدها إلى YYYY-MM-DD.
لا تفعل شيئاً على PostgreSQL (التاريخ هناك نوع حقيقي).
"""
from django.db import migrations

TABLES = {
    'halaqat_attendance': ['student_id'],
    'halaqat_teacherattendance': ['teacher_id', 'circle_id'],
    'halaqat_courseattendance': ['student_id', 'course_id'],
    'halaqat_courseteacherattendance': ['teacher_id', 'course_id'],
    'halaqat_teacherdailyattendance': ['teacher_id'],
    'halaqat_sabr': None,
}


def _norm(s):
    try:
        y, m, d = (int(x) for x in str(s)[:10].split('-'))
        return f'{y:04d}-{m:02d}-{d:02d}'
    except (ValueError, TypeError):
        return None


def forwards(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor != 'sqlite':
        return
    with conn.cursor() as cur:
        for table, keys in TABLES.items():
            cur.execute(f'SELECT id, date{"".join(", " + k for k in keys or [])} FROM {table} WHERE length(date) < 10')
            for row in cur.fetchall():
                rid, raw, key_vals = row[0], row[1], row[2:]
                new = _norm(raw)
                if not new or new == raw:
                    continue
                if keys:
                    where = ' AND '.join(f'{k} = %s' for k in keys)
                    cur.execute(f'SELECT id FROM {table} WHERE {where} AND date = %s AND id <> %s',
                                [*key_vals, new, rid])
                    if cur.fetchone():               # يوجد سجل بنفس اليوم بالصيغة الصحيحة → نحذف المكرر
                        cur.execute(f'DELETE FROM {table} WHERE id = %s', [rid])
                        continue
                cur.execute(f'UPDATE {table} SET date = %s WHERE id = %s', [new, rid])


class Migration(migrations.Migration):
    dependencies = [('halaqat', '0005_student_birth_date_sabr_notes')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
