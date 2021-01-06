# Generated by Django 3.1.4 on 2021-01-04 00:20

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inhouse', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='chanel_category',
            field=models.BigIntegerField(null=True, verbose_name='Categoria'),
        ),
        migrations.AddField(
            model_name='game',
            name='channel_blue',
            field=models.BigIntegerField(null=True, verbose_name='Blue-side'),
        ),
        migrations.AddField(
            model_name='game',
            name='channel_red',
            field=models.BigIntegerField(null=True, verbose_name='Red-side'),
        ),
        migrations.AddField(
            model_name='game',
            name='channel_text',
            field=models.BigIntegerField(null=True, verbose_name='Texto'),
        ),
        migrations.AlterField(
            model_name='gameparticipant',
            name='player',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='games', to='inhouse.player'),
        ),
        migrations.AlterField(
            model_name='playerrating',
            name='player',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ratings', to='inhouse.player'),
        ),
    ]