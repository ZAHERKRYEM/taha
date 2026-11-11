"""
إنشاء تقارير PDF عربية (من اليمين لليسار) لصفحة الإحصائيات.

يعتمد على:
  - reportlab           : بناء ملف PDF
  - arabic-reshaper     : وصل أحرف العربية (الأشكال الأولية/الوسطى/النهائية)
  - python-bidi         : ترتيب النص ثنائي الاتجاه (عربي + أرقام)
  - خط DejaVu Sans المرفق في static/halaqat/fonts (يدعم العربية، ومدمج في المشروع
    حتى يعمل على Render دون الحاجة لخطوط النظام)
"""
import io
import os
import datetime

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT

FONT = 'ArabicSans'
FONT_BOLD = 'ArabicSans-Bold'
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'halaqat', 'fonts')

GOLD = colors.HexColor('#B17F4A')
INK = colors.HexColor('#4A3420')
SOFT = colors.HexColor('#FAF7F2')
LINE = colors.HexColor('#E8D5B7')
C_PRESENT = colors.HexColor('#5A9367')
C_LATE = colors.HexColor('#D9A441')
C_ABSENT = colors.HexColor('#B5544B')
C_EXCUSED = colors.HexColor('#6B8CAE')

MONTHS_AR = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
             'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']

PAGE_W, PAGE_H = A4
MARGIN = 40
CONTENT_W = PAGE_W - 2 * MARGIN      # ≈ 515pt

_fonts_ready = False


def _register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    # خط «دبي» (Dubai) لتقارير PDF، مع الرجوع لـ DejaVu إن تعذّر تحميله
    try:
        pdfmetrics.registerFont(TTFont(FONT, os.path.join(_FONT_DIR, 'DUBAI-REGULAR.TTF')))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(_FONT_DIR, 'DUBAI-MEDIUM.TTF')))
        _load_cmap(os.path.join(_FONT_DIR, 'DUBAI-REGULAR.TTF'))
    except Exception:
        pdfmetrics.registerFont(TTFont(FONT, os.path.join(_FONT_DIR, 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, os.path.join(_FONT_DIR, 'DejaVuSans-Bold.ttf')))
    _fonts_ready = True


_FONT_CMAP = None
_FALLBACK_MAP = {}


def _load_cmap(path):
    """
    خط دبي لا يحوي «الأشكال المعزولة» من Presentation Forms-B (مثل ﺍ ﺏ ﺓ)،
    لكنه يحوي الحرف الأساسي نفسه (ا ب ة) وهو مطابق شكلاً؛ نحوّل إليه عند الحاجة.
    """
    global _FONT_CMAP, _FALLBACK_MAP
    import unicodedata
    from reportlab.pdfbase.ttfonts import TTFontFile
    _FONT_CMAP = set(TTFontFile(path).charToGlyph.keys())
    for cp in list(range(0xFB50, 0xFE00)) + list(range(0xFE70, 0xFF00)):
        if cp in _FONT_CMAP:
            continue
        dec = unicodedata.decomposition(chr(cp))
        if dec.startswith('<'):
            parts = dec.split()[1:]
            try:
                base = ''.join(chr(int(x, 16)) for x in parts)
            except ValueError:
                continue
            if all(ord(ch) in _FONT_CMAP for ch in base):
                _FALLBACK_MAP[cp] = base


# رمزا ligature للفظ الجلالة و«صلى الله عليه وسلم» (Presentation Forms-A) غير موجودين في
# بعض الخطوط فيظهران كمربع ☐؛ نعطّلهما ليُكتب النص حرفاً حرفاً (مع إبقاء وصل «لا» الصحيح).
_reshaper = arabic_reshaper.ArabicReshaper(configuration={
    'ARABIC LIGATURE ALLAH': False,
    'ARABIC LIGATURE SALLALLAHOU ALAYHE WASALLAM': False,
})


def ar(text):
    """يجهّز نص عربي للعرض: وصل الأحرف ثم ترتيب الاتجاه."""
    out = get_display(_reshaper.reshape(str(text)))
    if _FALLBACK_MAP:
        out = out.translate(_FALLBACK_MAP)
    return out


def _fit(text, font, size, max_width):
    """يقصّ النص الطويل بـ … حتى لا يتجاوز عرض العمود (لا التفاف في الجداول)."""
    text = str(text)
    if pdfmetrics.stringWidth(ar(text), font, size) <= max_width:
        return text
    while len(text) > 1 and pdfmetrics.stringWidth(ar(text + '…'), font, size) > max_width:
        text = text[:-1]
    return text + '…'


def _pct(v):
    return f'{v}%' if v is not None else '—'


def _month_label(first):
    return f'{MONTHS_AR[first.month - 1]} {first.year}'


# ---------------------------------------------------------------- جداول

def _rtl_table(header, rows, widths, name_cols=(0,), header_colors=None, size=9):
    """
    جدول من اليمين لليسار: العمود المنطقي الأول يظهر في أقصى اليمين.
    header_colors: {index: color} لتلوين رؤوس أعمدة معيّنة (فهرس منطقي).
    """
    n = len(header)

    def prep(row, is_header=False):
        cells = []
        for i, c in enumerate(row):
            if i in name_cols and not is_header:
                c = _fit(c, FONT, size, widths[i] - 10)
            cells.append(ar(c) if isinstance(c, str) else str(c))
        return cells[::-1]                      # عكس الترتيب ليبدأ العمود الأول من اليمين

    data = [prep(header, True)] + [prep(r) for r in rows]
    t = Table(data, colWidths=widths[::-1], repeatRows=1)
    style = [
        ('FONTNAME', (0, 0), (-1, -1), FONT),
        ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), size),
        ('TEXTCOLOR', (0, 0), (-1, -1), INK),
        ('BACKGROUND', (0, 0), (-1, 0), GOLD),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, SOFT]),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE),
    ]
    for i in name_cols:
        style.append(('ALIGN', (n - 1 - i, 1), (n - 1 - i, -1), 'RIGHT'))
        style.append(('RIGHTPADDING', (n - 1 - i, 0), (n - 1 - i, -1), 8))
    for i, col in (header_colors or {}).items():
        style.append(('BACKGROUND', (n - 1 - i, 0), (n - 1 - i, 0), col))
    t.setStyle(TableStyle(style))
    return t


def _heading(text, size=13):
    st = ParagraphStyle('h', fontName=FONT_BOLD, fontSize=size, leading=size + 6,
                        alignment=TA_RIGHT, textColor=INK, spaceBefore=8, spaceAfter=5, keepWithNext=1)
    return Paragraph(ar(text), st)


def _line(text, size=9.5, color=INK, keep=False):
    st = ParagraphStyle('l', fontName=FONT, fontSize=size, leading=size + 5,
                        alignment=TA_RIGHT, textColor=color,
                        keepWithNext=1 if keep else 0, spaceAfter=3 if keep else 0)
    return Paragraph(ar(text), st)


def _banner(text):
    t = Table([[ar(text)]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GOLD),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), FONT_BOLD),
        ('FONTSIZE', (0, 0), (-1, -1), 15),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
    ]))
    return t


# ---------------------------------------------------------------- الرسم اليومي

def _daily_chart(days):
    """أعمدة مكدّسة 100% لكل يوم/أسبوع/شهر؛ الأقدم عند اليمين (اتجاه عربي)."""
    H = 125
    base, top_pad, side = 22, 14, 22
    plot_h = H - base - top_pad
    d = Drawing(CONTENT_W, H)
    n = len(days)
    slot = (CONTENT_W - 2 * side) / max(n, 1)
    bar_w = slot * 0.68
    every = max(1, -(-n // 31))

    for v in (0, 50, 100):
        y = base + v / 100 * plot_h
        d.add(Line(side, y, CONTENT_W - side, y, strokeColor=LINE, strokeWidth=0.5))
        d.add(String(side - 3, y - 2, f'{v}%', fontName=FONT, fontSize=6, fillColor=colors.grey, textAnchor='end'))

    for i, day in enumerate(days):
        x = CONTENT_W - side - (i + 1) * slot + (slot - bar_w) / 2
        y = base
        total = day['total']
        if total:
            for key, col in (('present', C_PRESENT), ('late', C_LATE),
                             ('absent', C_ABSENT), ('excused', C_EXCUSED)):
                h = day[key] / total * plot_h
                if h > 0:
                    d.add(Rect(x, y, bar_w, h, fillColor=col, strokeColor=None))
                    y += h
        else:
            d.add(Rect(x, y, bar_w, plot_h, fillColor=SOFT, strokeColor=None))
        if i % every == 0:
            d.add(String(x + bar_w / 2, base - 10, ar(day['label']), fontName=FONT, fontSize=6,
                         fillColor=INK, textAnchor='middle'))
    return d


def _legend():
    items = [('حاضر', C_PRESENT), ('تأخر', C_LATE), ('غياب', C_ABSENT), ('إذن', C_EXCUSED)]
    d = Drawing(CONTENT_W, 14)
    x = CONTENT_W - 6
    for label, col in items:
        d.add(Rect(x - 12, 3, 12, 6, fillColor=col, strokeColor=None))
        text = ar(label)
        d.add(String(x - 16, 3, text, fontName=FONT, fontSize=8, fillColor=INK, textAnchor='end'))
        x -= 16 + pdfmetrics.stringWidth(text, FONT, 8) + 16
    return d


# ---------------------------------------------------------------- الأقسام

def _p(v):
    return f'{v}%'


def _population_section(kind, title, st):
    """kind: 'students' | 'staff' — كل القيم نسب مئوية من مجموع السجلات."""
    out = [_heading(title, 14)]
    if st['total'] == 0:
        out.append(_line('لا توجد سجلات حضور في هذه الفترة ضمن الفلاتر المحددة.', color=colors.grey))
        out.append(Spacer(1, 8))
        return out

    # الملخص
    out.append(_rtl_table(
        ['نسبة الحضور', 'العدد', 'أيام الدوام', 'حاضر', 'تأخر', 'غائب', 'إذن'],
        [[_pct(st['rate']), st['people_total'], st['session_days'], _p(st['pct_present']), _p(st['pct_late']),
          _p(st['pct_absent']), _p(st['pct_excused'])]],
        [85, 65, 70, 74, 74, 74, 73], name_cols=(),
        header_colors={3: C_PRESENT, 4: C_LATE, 5: C_ABSENT, 6: C_EXCUSED}, size=10))
    out.append(Spacer(1, 10))

    if st.get('monthly'):
        rows = [[m['label'], _pct(m['rate']), _p(m['pct_present']), _p(m['pct_late']), _p(m['pct_absent']),
                 _p(m['pct_excused']), m['total']] for m in st['monthly']]
        if len(st['monthly']) > 1 and st.get('monthly_avg'):
            a = st['monthly_avg']
            rows.append(['المتوسط الشهري', _pct(a['rate']), _p(a['pct_present']), _p(a['pct_late']),
                         _p(a['pct_absent']), _p(a['pct_excused']), a['total']])
        rows.append(['المجمل للفترة', _pct(st['rate']), _p(st['pct_present']), _p(st['pct_late']),
                     _p(st['pct_absent']), _p(st['pct_excused']), st['total']])
        out.append(_line('التفصيل الشهري', 10.5, keep=True))
        out.append(_rtl_table(['الشهر', 'نسبة الحضور', 'حاضر', 'تأخر', 'غائب', 'إذن', 'السجلات'], rows,
                              [115, 70, 62, 62, 62, 62, 82],
                              header_colors={2: C_PRESENT, 3: C_LATE, 4: C_ABSENT, 5: C_EXCUSED}))
        out.append(Spacer(1, 10))

    mode_lbl = {'day': 'اليومي', 'week': 'الأسبوعي', 'month': 'الشهري'}[st['chart_mode']]
    out.append(KeepTogether([_line(f'توزّع الحضور {mode_lbl} (٪)', 10.5), Spacer(1, 3),
                             _daily_chart(st['chart']), _legend()]))
    out.append(Spacer(1, 8))

    out.append(_line('حسب المصدر', 10.5, keep=True))
    out.append(_rtl_table(
        ['المصدر', 'نسبة الحضور', 'حاضر', 'تأخر', 'غائب', 'إذن'],
        [[r['label'], _pct(r['rate']), _p(r['pct_present']), _p(r['pct_late']), _p(r['pct_absent']), _p(r['pct_excused'])]
         for r in st['sources']],
        [195, 70, 62, 62, 62, 64], header_colors={2: C_PRESENT, 3: C_LATE, 4: C_ABSENT, 5: C_EXCUSED}))
    out.append(Spacer(1, 10))

    if kind == 'students':
        out.append(_line(f'سجل الطلاب ({st["people_total"]} طالب)', 10.5, keep=True))
        out.append(_rtl_table(
            ['الاسم', 'الحلقة', 'العمر', 'السبر', 'الحضور', 'حاضر', 'تأخر', 'غائب', 'إذن'],
            [[p['name'], p['sub'], p.get('age') if p.get('age') is not None else '—', p.get('sabr', 0), _pct(p['rate']),
              _p(p['pct_present']), _p(p['pct_late']), _p(p['pct_absent']), _p(p['pct_excused'])]
             for p in st['people']],
            [120, 90, 32, 32, 46, 48, 48, 48, 51], name_cols=(0, 1),
            header_colors={5: C_PRESENT, 6: C_LATE, 7: C_ABSENT, 8: C_EXCUSED}))
    else:
        out.append(_line(f'سجل الكادر ({st["people_total"]})', 10.5, keep=True))
        out.append(_rtl_table(
            ['الاسم', 'الحضور', 'حاضر', 'تأخر', 'غائب', 'إذن'],
            [[p['name'], _pct(p['rate']), _p(p['pct_present']), _p(p['pct_late']), _p(p['pct_absent']), _p(p['pct_excused'])]
             for p in st['people']],
            [215, 60, 60, 60, 60, 60],
            header_colors={2: C_PRESENT, 3: C_LATE, 4: C_ABSENT, 5: C_EXCUSED}))
    out.append(Spacer(1, 14))
    return out


def _sabr_section(sb):
    out = [_heading('السبر', 14)]
    out.append(_rtl_table(
        ['عدد مرات السبر', 'نسبة الطلاب الذين سُبِروا', 'سُبِروا / الطلاب', 'متوسط لكل طالب'],
        [[sb['count'], f"{sb['pct']}%", f"{sb['done']} / {sb['students']}", sb['avg']]],
        [120, 150, 125, 120], name_cols=(), size=10))
    out.append(Spacer(1, 8))
    if sb['circles']:
        out.append(_line('حسب الحلقة', 10.5, keep=True))
        out.append(_rtl_table(['الحلقة', 'الطلاب', 'سُبِروا', 'النسبة', 'مرات السبر'],
                              [[r['label'], r['students'], r['done'], f"{r['pct']}%", r['count']] for r in sb['circles']],
                              [195, 75, 75, 85, 85]))
    out.append(Spacer(1, 14))
    return out


# ---------------------------------------------------------------- الدالة الرئيسية

def build_stats_pdf(ctx):
    """يبني تقرير PDF من سياق الإحصائيات (_stats_context) ويعيد bytes."""
    _register_fonts()
    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(colors.grey)
        canvas.drawCentredString(PAGE_W / 2, 22, ar(f'صفحة {doc.page}'))
        canvas.drawRightString(PAGE_W - MARGIN, 22, ar('مسجد طه — تقرير الإحصائيات'))
        canvas.setStrokeColor(LINE)
        canvas.line(MARGIN, 34, PAGE_W - MARGIN, 34)
        canvas.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                          topMargin=MARGIN, bottomMargin=48,
                          title='تقرير إحصائيات مسجد طه', author='مسجد طه')
    doc.addPageTemplates([PageTemplate(
        id='main', onPage=footer,
        frames=[Frame(MARGIN, 48, CONTENT_W, PAGE_H - MARGIN - 48, id='f',
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])

    who_label = {'students': 'الطلاب فقط', 'staff': 'الكادر فقط', 'both': 'الطلاب والكادر'}[ctx['who']]
    scope_label = f"حلقة {ctx['circle'].name}" if ctx['circle'] else 'كامل المسجد (حلقات + دورات + تفقد عام)'
    now = datetime.datetime.now()

    story = [
        _banner('تقرير إحصائيات الحضور — مسجد طه'),
        Spacer(1, 8),
        _line(f"الفترة: من {ctx['start']:%Y-%m-%d} إلى {ctx['end']:%Y-%m-%d}", 10.5),
        _line(f'النطاق: {scope_label}', 10.5),
        _line(f'الفئة: {who_label}', 10.5),
        *([_line('العمر: ' + ' '.join(x for x in (
            f"من {ctx['age_min']}" if ctx.get('age_min') is not None else '',
            f"إلى {ctx['age_max']}" if ctx.get('age_max') is not None else '') if x), 10.5)]
          if ctx.get('age_min') is not None or ctx.get('age_max') is not None else []),
        _line(f"تاريخ إنشاء التقرير: {now:%Y-%m-%d %H:%M}", 8.5, colors.grey),
        _line('نسبة الحضور = (حاضر + تأخر) ÷ (حاضر + تأخر + غائب)، ولا يُحتسب الإذن.', 8.5, colors.grey),
        Spacer(1, 6),
    ]
    if ctx['students_stats'] is not None:
        story += _population_section('students', 'الطلاب', ctx['students_stats'])
    if ctx.get('sabr_stats'):
        story += _sabr_section(ctx['sabr_stats'])
    if ctx['staff_stats'] is not None:
        story += _population_section('staff', 'الكادر', ctx['staff_stats'])

    doc.build(story)
    return buf.getvalue()
