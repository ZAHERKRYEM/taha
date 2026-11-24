from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('halaqat', '0007_recitation'),
    ]

    operations = [
        migrations.CreateModel(
            name='AssistantQuery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user', models.CharField(max_length=150, verbose_name='المستخدم')),
                ('question', models.CharField(blank=True, default='', max_length=500, verbose_name='السؤال')),
                ('spec', models.TextField(blank=True, default='', verbose_name='المواصفة (JSON)')),
                ('via', models.CharField(choices=[('ai', 'سؤال بالذكاء الاصطناعي'), ('manual', 'تعديل يدوي')], default='ai', max_length=10, verbose_name='الطريقة')),
                ('rows', models.PositiveIntegerField(default=0, verbose_name='عدد الصفوف')),
                ('ok', models.BooleanField(default=True, verbose_name='نجح')),
                ('error', models.CharField(blank=True, default='', max_length=255, verbose_name='الخطأ')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='الوقت')),
            ],
            options={
                'verbose_name': 'سؤال للمساعد',
                'verbose_name_plural': 'أسئلة المساعد الإحصائي',
                'ordering': ['-created_at', '-id'],
            },
        ),
    ]
