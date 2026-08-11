from django import forms
from django.utils import timezone
from .models import Teacher, Circle, Student, Course


class TeacherForm(forms.ModelForm):
    class Meta:
        model = Teacher
        fields = ['name', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'اسم الأستاذ الجديد'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف (اختياري)'}),
        }


class CircleForm(forms.ModelForm):
    # حقل اختياري لإضافة أستاذ جديد مباشرة من نفس النموذج
    new_teacher_name = forms.CharField(
        label='أو أضف أستاذاً جديداً',
        max_length=150, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'اسم الأستاذ الجديد (اختياري)'})
    )

    class Meta:
        model = Circle
        fields = ['name', 'teacher', 'description']
        labels = {
            'name': 'اسم الحلقة',
            'teacher': 'الأستاذ المسؤول',
            'description': 'وصف مختصر',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'مثال: حلقة الأنعام'}),
            'description': forms.TextInput(attrs={'placeholder': 'وصف مختصر (اختياري)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].required = False
        self.fields['teacher'].empty_label = 'اختر أستاذاً موجوداً'

    def save(self, commit=True):
        new_name = self.cleaned_data.get('new_teacher_name')
        if new_name:
            teacher, _ = Teacher.objects.get_or_create(name=new_name.strip())
            self.instance.teacher = teacher
        return super().save(commit=commit)


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ['name', 'circle', 'phone', 'notes']
        labels = {
            'name': 'اسم الطالب',
            'circle': 'الحلقة',
            'phone': 'رقم الهاتف',
            'notes': 'ملاحظات',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'الاسم الكامل'}),
            'phone': forms.TextInput(attrs={'placeholder': 'رقم الهاتف (اختياري)'}),
            'notes': forms.TextInput(attrs={'placeholder': 'رقم ولي الأمر، ملاحظات... (اختياري)'}),
        }


class WhatsAppAbsentForm(forms.Form):
    date = forms.DateField(
        label='تاريخ الغياب',
        initial=timezone.now().date(),
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    circle = forms.ModelChoiceField(
        queryset=Circle.objects.none(),
        required=False,
        label='الحلقة (اختياري)',
        empty_label='كل الحلقات'
    )
    message = forms.CharField(
        label='نص الرسالة',
        widget=forms.Textarea(attrs={
            'rows': 6,
            'placeholder': 'مثال: السلام عليكم ورحمة الله وبركاته\nحياكم الله\n🔴 لأخذ العلم قد تغيب ابنكم {student_name} عن المسجد اليوم {date}.\n👈🏻 يرجى منكم تبرير الغياب في المرات القادمة قبل الغياب\n    ولكم جزيل الشكر🌷\n\nإدارة المسجد',
        }),
        initial='🍀 السلام عليكم ورحمة الله وبركاته\n      حياكم الله\n🔴 لأخذ العلم قد تغيب ابنكم {student_name} عن المسجد اليوم {date}.\n👈🏻 يرجى منكم تبرير الغياب في المرات\n      القادمة قبل الغياب\n      ولكم جزيل الشكر🌷\n\nإدارة المسجد',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['circle'].queryset = Circle.objects.all()


class StudentMultipleChoiceField(forms.ModelMultipleChoiceField):
    """يعرض اسم الطالب مع اسم حلقته لتسهيل الاختيار من قائمة طويلة"""
    def label_from_instance(self, obj):
        return f'{obj.name} — {obj.circle.name}'


class CourseForm(forms.ModelForm):
    # حقل اختياري لإضافة أستاذ/محاضر جديد مباشرة من نفس النموذج
    new_teacher_name = forms.CharField(
        label='أو أضف أستاذاً/محاضراً جديداً',
        max_length=150, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'اسم الأستاذ الجديد (اختياري)'})
    )
    students = StudentMultipleChoiceField(
        queryset=Student.objects.select_related('circle').order_by('circle__name', 'name'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='الطلاب المشاركون',
    )

    class Meta:
        model = Course
        fields = ['name', 'teacher', 'description', 'students']
        labels = {
            'name': 'اسم الدورة / الدرس',
            'teacher': 'الأستاذ / المحاضر المسؤول',
            'description': 'وصف مختصر',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'مثال: دورة تحسين التلاوة'}),
            'description': forms.TextInput(attrs={'placeholder': 'وصف مختصر (اختياري)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].required = False
        self.fields['teacher'].empty_label = 'اختر أستاذاً موجوداً (اختياري)'

    def save(self, commit=True):
        new_name = self.cleaned_data.get('new_teacher_name')
        if new_name:
            teacher, _ = Teacher.objects.get_or_create(name=new_name.strip())
            self.instance.teacher = teacher
        return super().save(commit=commit)
