"""تصدير نتيجة المساعد الإحصائي إلى Excel (openpyxl): ورقة من اليمين لليسار بأرقام حقيقية قابلة للفرز والتصفية."""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill('solid', fgColor='B17F4A')
SUMMARY_FILL = PatternFill('solid', fgColor='F1E6D3')
HEADER_FONT = Font(bold=True, color='FFFFFF', size=11)
THIN = Side(style='thin', color='E8D5B7')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def build_xlsx(result):
    """يعيد bytes لملف xlsx: العنوان، سطر «كيف فهمتُ سؤالك»، الجدول، صف الإجمالي، الملاحظات."""
    cols, rows, summary = result['columns'], result['rows'], result.get('summary')
    wb = Workbook()
    ws = wb.active
    ws.title = 'النتائج'
    ws.sheet_view.rightToLeft = True
    n = max(1, len(cols))

    ws.append([result['title']])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    ws['A1'].font = Font(bold=True, size=14, color='4A3420')
    ws['A1'].alignment = Alignment(horizontal='right')
    ws.append([result['understood']])
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n)
    ws['A2'].alignment = Alignment(horizontal='right', wrap_text=True, vertical='top')
    ws['A2'].font = Font(size=10, color='7A6A55')
    ws.row_dimensions[2].height = 32
    ws.append([])

    header_row = 4
    ws.append([c['label'] for c in cols])
    for cell in ws[header_row]:
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    ws.row_dimensions[header_row].height = 30

    def style_row(r, bold=False, fill=None):
        for i, c in enumerate(cols, start=1):
            cell = ws.cell(row=r, column=i)
            cell.border = BORDER
            if fill:
                cell.fill = fill
            cell.font = Font(bold=bold, color='4A3420')
            if c['kind'] == 'text':
                cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='center', vertical='center')
                cell.number_format = '0"%"' if c['kind'] == 'pct' else '0'

    for row in rows:
        ws.append([('' if v is None else v) for v in row])
        style_row(ws.max_row)
    last_data = ws.max_row

    if summary:
        ws.append([('' if v is None else v) for v in summary])
        style_row(ws.max_row, bold=True, fill=SUMMARY_FILL)

    ws.append([])
    for note in result.get('notes') or []:
        ws.append([note])
        r = ws.max_row
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=n)
        ws.cell(row=r, column=1).font = Font(size=9, color='9C8A71')
        ws.cell(row=r, column=1).alignment = Alignment(horizontal='right', wrap_text=True)

    # عرض الأعمدة حسب أطول محتوى
    for i, c in enumerate(cols, start=1):
        longest = max([len(str(c['label']))] + [len(str(r[i - 1])) for r in rows[:300] if r[i - 1] is not None] + [4])
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, longest + 3), 42 if c['kind'] == 'text' else 18)

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if rows:
        ws.auto_filter.ref = f'A{header_row}:{get_column_letter(n)}{last_data}'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
