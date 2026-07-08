from django import forms
from .models import Teacher, Circle, Student


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
        fields = ['name', 'circle', 'notes']
        labels = {
            'name': 'اسم الطالب',
            'circle': 'الحلقة',
            'notes': 'ملاحظات',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'الاسم الكامل'}),
            'notes': forms.TextInput(attrs={'placeholder': 'رقم ولي الأمر، ملاحظات... (اختياري)'}),
        }
